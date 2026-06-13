"""tests for the gate's regression logic — the core of the thing.

covers the cases that matter:
- regression (baseline pass + candidate fail) -> block
- no regression -> pass
- newly-fixed counted but doesn't block
- empty suite + all-pass/all-fail edges
plus the end-to-end db-backed gate and cache/demo-mode behavior.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("RECOIL_JUDGE_PROVIDER", "mock")

from recoil.gate.engine import classify_cases, verdict_for, GateError  # noqa: E402


def _case(cid: str, title: str = "case", severity: str = "medium") -> dict:
    return {"id": cid, "title": title, "severity": severity}


# ---------------------------------------------------------------------------
# pure classification logic
# ---------------------------------------------------------------------------

def test_regression_blocks():
    cases = [_case("a"), _case("b")]
    cls = classify_cases(cases, {"a": True, "b": True}, {"a": False, "b": True})
    kinds = {c.eval_case_id: c.kind for c in cls}
    assert kinds["a"] == "regression"
    assert kinds["b"] == "still_passing"
    assert verdict_for(cls) == "BLOCK"


def test_no_regression_passes():
    cases = [_case("a"), _case("b")]
    cls = classify_cases(cases, {"a": True, "b": False}, {"a": True, "b": False})
    assert verdict_for(cls) == "PASS"
    kinds = {c.eval_case_id: c.kind for c in cls}
    assert kinds["a"] == "still_passing"
    assert kinds["b"] == "still_failing"


def test_newly_fixed_counted_but_not_blocking():
    cases = [_case("a"), _case("b")]
    cls = classify_cases(cases, {"a": False, "b": True}, {"a": True, "b": True})
    kinds = {c.eval_case_id: c.kind for c in cls}
    assert kinds["a"] == "newly_fixed"
    assert verdict_for(cls) == "PASS"
    assert sum(1 for c in cls if c.kind == "newly_fixed") == 1


def test_newly_fixed_does_not_mask_regression():
    cases = [_case("a"), _case("b")]
    cls = classify_cases(cases, {"a": False, "b": True}, {"a": True, "b": False})
    assert verdict_for(cls) == "BLOCK"


def test_empty_suite_passes():
    cls = classify_cases([], {}, {})
    assert cls == []
    assert verdict_for(cls) == "PASS"


def test_all_pass():
    cases = [_case(c) for c in "abc"]
    cls = classify_cases(cases, {c: True for c in "abc"}, {c: True for c in "abc"})
    assert verdict_for(cls) == "PASS"
    assert all(c.kind == "still_passing" for c in cls)


def test_all_fail_is_not_a_regression():
    # baseline already failed these, so candidate failing too isn't a regression
    cases = [_case(c) for c in "abc"]
    cls = classify_cases(cases, {c: False for c in "abc"}, {c: False for c in "abc"})
    assert verdict_for(cls) == "PASS"
    assert all(c.kind == "still_failing" for c in cls)


def test_new_case_without_baseline_result_not_blocking():
    cases = [_case("a"), _case("new")]
    cls = classify_cases(cases, {"a": True}, {"a": True, "new": False})
    kinds = {c.eval_case_id: c.kind for c in cls}
    assert kinds["new"] == "new_case"
    assert verdict_for(cls) == "PASS"


def test_missing_candidate_result_is_an_error():
    with pytest.raises(GateError):
        classify_cases([_case("a")], {"a": True}, {})


# ---------------------------------------------------------------------------
# end-to-end against a seeded db (the scripted demo path)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seeded_conn(tmp_path_factory):
    from recoil import config, db

    db_path = tmp_path_factory.mktemp("recoil") / "test.db"
    conn = db.reset_db(db_path)
    from recoil.seeding import seed_all

    summary = seed_all(conn)
    return conn, summary


def test_seed_shape(seeded_conn):
    from recoil import db

    conn, summary = seeded_conn
    assert summary["runs"] >= 240
    assert len(summary["cases"]) == 12
    assert db.get_published_version(conn)["label"] == "v_good"
    severities = {c["severity"] for c in db.list_eval_cases(conn)}
    assert "critical" in severities and "low" in severities


def test_gate_blocks_v_regressed(seeded_conn):
    from recoil.gate import run_gate

    conn, summary = seeded_conn
    report = run_gate(conn, candidate="v_regressed", persist=False)
    assert report.verdict == "BLOCK"
    assert summary["cases"]["hero_after_hours_outage"] in report.regressed_case_ids
    assert report.baseline_label == "v_good"


def test_gate_passes_v_fixed(seeded_conn):
    from recoil.gate import run_gate

    conn, _ = seeded_conn
    report = run_gate(conn, candidate="v_fixed", persist=False)
    assert report.verdict == "PASS"
    assert report.regressed_case_ids == []
    assert report.passed_count == report.total_cases


def test_gate_serves_from_cache_in_demo_mode(seeded_conn):
    """demo determinism: every demo-path verdict should come from cache."""
    from recoil import db
    from recoil.evals.runner import judge_case

    conn, _ = seeded_conn
    v = db.get_version_by_label(conn, "v_regressed")
    for case in db.list_eval_cases(conn, status="active"):
        result = judge_case(conn, case, v, use_cache=True)
        assert result["from_cache"] is True


def test_unknown_candidate_raises(seeded_conn):
    from recoil.gate import run_gate

    conn, _ = seeded_conn
    with pytest.raises(GateError):
        run_gate(conn, candidate="v_nonexistent", persist=False)
