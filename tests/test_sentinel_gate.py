"""sentinel tests: claim verification + freeze/replay regression gate.
no model calls — we inject the replay generator."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("RECOIL_JUDGE_PROVIDER", "mock")

from recoil import db  # noqa: E402
from recoil.sentinel.agent import Finding, IntelReport, verify_report  # noqa: E402
from recoil.sentinel.gate import (  # noqa: E402
    freeze_failure,
    list_sentinel_cases,
    replay_frozen_cases,
)
from recoil.sentinel.publish import _ensure_sentinel_version  # noqa: E402


def _snapshot() -> dict:
    return {
        "fetched_at": "2026-06-12T00:00:00+00:00",
        "metrics": {
            "price:bitcoin": {
                "label": "Bitcoin price (USD)",
                "value": 63769.0,
                "unit": "usd",
                "source": "CoinGecko",
                "source_url": "https://example.test/cg",
                "extra": {},
            },
            "tvl:protocol:lido": {
                "label": "Lido TVL (USD)",
                "value": 14978330341.78,
                "unit": "usd",
                "source": "DefiLlama",
                "source_url": "https://example.test/llama",
                "extra": {},
            },
        },
        "source_errors": [],
    }


def _report(btc_value: float, *, metric: str = "price:bitcoin") -> IntelReport:
    return IntelReport(
        title="t",
        executive_summary="s",
        findings=[
            Finding(
                headline="BTC level",
                body="BTC trades around this level.",
                metric_keys=[metric],
                claimed_values={metric: btc_value},
                signal="neutral",
            ),
            Finding(
                headline="Lido",
                body="Lido leads TVL.",
                metric_keys=["tvl:protocol:lido"],
                claimed_values={"tvl:protocol:lido": 14978330341.78},
                signal="neutral",
            ),
            Finding(
                headline="Qualitative",
                body="No drama today.",
                metric_keys=["price:bitcoin"],
                claimed_values={},
                signal="neutral",
            ),
        ],
        risk_flags=[],
        confidence="medium",
    )


# ---------------------------------------------------------------------------
# verifier
# ---------------------------------------------------------------------------

def test_verify_passes_exact_and_rounded():
    snap = _snapshot()
    assert verify_report(_report(63769.0), snap).passed
    assert verify_report(_report(63800.0), snap).passed  # within 1% tolerance, still ok


def test_verify_fails_wrong_value():
    result = verify_report(_report(70000.0), _snapshot())
    assert not result.passed
    assert any("price:bitcoin" in p for p in result.problems)


def test_verify_fails_hallucinated_metric():
    result = verify_report(_report(1.0, metric="price:dogecoin"), _snapshot())
    assert not result.passed
    assert any("hallucinated" in p for p in result.problems)


# ---------------------------------------------------------------------------
# freeze + replay gate
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    return db.reset_db(tmp_path / "sentinel.db")


def _freeze_bad_report(conn) -> str:
    snap = _snapshot()
    bad = _report(70000.0)
    verification = verify_report(bad, snap)
    version = _ensure_sentinel_version(conn)
    run_id = db.insert_run(
        conn,
        agent_version_id=version["id"],
        input={"kind": "sentinel_intel"},
        output={"report": bad.model_dump()},
        spans=[],
        ground_truth_ref="test",
        latency_ms=1.0,
        total_cost_usd=0.0,
    )
    return freeze_failure(
        conn, run_id=run_id, report=bad, snapshot=snap, verification=verification
    )


def test_freeze_creates_replayable_case(conn):
    case_id = _freeze_bad_report(conn)
    cases = list_sentinel_cases(conn)
    assert [c["id"] for c in cases] == [case_id]
    assert cases[0]["input"]["frozen_snapshot"]["metrics"]["price:bitcoin"]["value"] == 63769.0
    assert cases[0]["first_failed_version_id"] is not None
    assert cases[0]["fixed_in_version_id"] is None


def test_replay_fixed_then_regressed_blocks(conn):
    _freeze_bad_report(conn)

    good = lambda snap: (_report(63769.0), {})  # noqa: E731
    bad = lambda snap: (_report(70000.0), {})  # noqa: E731

    # agent fixed it -> case passes, gets stamped fixed_in, verdict pass
    result = replay_frozen_cases(conn, generate=good)
    assert result["verdict"] == "PASS"
    assert len(result["newly_fixed"]) == 1
    assert list_sentinel_cases(conn)[0]["fixed_in_version_id"] is not None

    # agent breaks it again -> a fixed case fails -> regression -> block
    result = replay_frozen_cases(conn, generate=bad)
    assert result["verdict"] == "BLOCK"
    assert len(result["regressions"]) == 1


def test_replay_never_fixed_does_not_block(conn):
    _freeze_bad_report(conn)
    bad = lambda snap: (_report(70000.0), {})  # noqa: E731
    result = replay_frozen_cases(conn, generate=bad)
    assert result["verdict"] == "PASS"  # still failing but never fixed: reported, doesn't block
    assert len(result["still_failing"]) == 1


def test_replay_agent_crash_reads_as_fail_not_crash(conn):
    _freeze_bad_report(conn)

    def boom(snap):
        raise RuntimeError("api down")

    result = replay_frozen_cases(conn, generate=boom)
    assert result["verdict"] == "PASS"
    assert len(result["still_failing"]) == 1


def test_replay_with_no_cases_is_clean(conn):
    result = replay_frozen_cases(conn, generate=lambda s: (_report(1.0), {}))
    assert result == {
        "checked": 0,
        "regressions": [],
        "still_failing": [],
        "newly_fixed": [],
        "verdict": "PASS",
    }
