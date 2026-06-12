"""Phase F — the Recoil regression gate over real Sentinel reports.

Recoil DNA applied to the autonomous publisher:

- freeze_failure(): when a report fails claim verification, the exact failure
  is frozen as a permanent eval case — input snapshot, failing report, and the
  verifier's problems — with first_failed_version_id = sentinel_v1.
- replay_frozen_cases(): before any future publish, the agent is re-run
  against the FROZEN snapshots of past failures (ground truth pinned at
  capture time, so replays are deterministic on the data side) and re-verified.
  * a case that was previously fixed and fails again  -> REGRESSION -> BLOCK
  * a case that has never passed and still fails      -> reported, not blocking
  * a failing case that now passes                    -> stamped fixed_in

This gives Sentinel the original product guarantee: it cannot republish a
mistake it has already learned from.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Callable, Optional

from .. import db
from ..judge import output_hash
from .agent import IntelReport, VerificationResult, generate_report, verify_report
from .publish import SENTINEL_VERSION_LABEL, _ensure_sentinel_version

log = logging.getLogger("recoil.sentinel")

SENTINEL_CASE_KIND = "sentinel_replay"

# replay cost control: each replayed case is one live model call
DEFAULT_REPLAY_LIMIT = 3


def freeze_failure(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    report: IntelReport,
    snapshot: dict[str, Any],
    verification: VerificationResult,
) -> str:
    """Freeze a failed report into a permanent regression case."""
    version = _ensure_sentinel_version(conn)
    title = f"Report must verify: {verification.problems[0][:70]}" if verification.problems else (
        "Report failed claim verification"
    )
    case_id = db.insert_eval_case(
        conn,
        source_run_id=run_id,
        title=title,
        input={
            "kind": SENTINEL_CASE_KIND,
            "frozen_snapshot": snapshot,
        },
        context_snapshot={
            "ground_truth_source": "frozen live snapshot (CoinGecko+DefiLlama) at "
            + snapshot.get("fetched_at", "?"),
            "failing_report": report.model_dump(),
            "problems": verification.problems,
        },
        rubric=(
            "Re-run the Sentinel agent against the frozen snapshot. Every numeric claim in the "
            "regenerated report must verify against that snapshot (1% tolerance); no claim may "
            "cite a metric absent from the snapshot."
        ),
        reference_behavior=(
            "All claims grounded: every finding cites only frozen-snapshot metrics and echoes "
            "their values within tolerance."
        ),
        severity="high",
        first_failed_version_id=version["id"],
    )
    db.upsert_eval_result(
        conn,
        eval_case_id=case_id,
        agent_version_id=version["id"],
        passed=False,
        score=max(0.0, 1.0 - 0.25 * len(verification.problems)),
        judge_rationale="; ".join(verification.problems) or "claim verification failed",
        actual_output=report.model_dump(),
        output_hash=output_hash(report.model_dump()),
    )
    log.warning("sentinel failure FROZEN as regression case %s", case_id[:8])
    return case_id


def list_sentinel_cases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        c
        for c in db.list_eval_cases(conn, status="active")
        if c["input"].get("kind") == SENTINEL_CASE_KIND
    ]


GenerateFn = Callable[[dict[str, Any]], tuple[IntelReport, dict[str, Any]]]


def replay_frozen_cases(
    conn: sqlite3.Connection,
    *,
    limit: int = DEFAULT_REPLAY_LIMIT,
    generate: Optional[GenerateFn] = None,
) -> dict[str, Any]:
    """Replay up to `limit` most-recent frozen sentinel cases against the
    current agent. Returns:
      {checked, regressions: [case], still_failing: [case], newly_fixed: [case],
       verdict: "PASS"|"BLOCK"}
    BLOCK iff a previously-fixed case fails again. `generate` is injectable
    for tests; defaults to the live agent.
    """
    generate = generate or generate_report
    version = _ensure_sentinel_version(conn)
    cases = list_sentinel_cases(conn)
    cases.sort(key=lambda c: c["created_at"], reverse=True)
    cases = cases[: max(limit, 0)]

    regressions: list[dict[str, Any]] = []
    still_failing: list[dict[str, Any]] = []
    newly_fixed: list[dict[str, Any]] = []

    for case in cases:
        snapshot = case["input"]["frozen_snapshot"]
        try:
            report, _stats = generate(snapshot)
            verification = verify_report(report, snapshot)
            passed = verification.passed
            rationale = (
                "all claims grounded on replay"
                if passed
                else "; ".join(verification.problems)
            )
            actual = report.model_dump()
        except Exception as exc:  # a broken agent must read as FAIL, not crash the gate
            passed = False
            rationale = f"[replay error] agent failed on frozen snapshot: {exc}"
            actual = {}

        db.upsert_eval_result(
            conn,
            eval_case_id=case["id"],
            agent_version_id=version["id"],
            passed=passed,
            score=1.0 if passed else 0.0,
            judge_rationale=rationale,
            actual_output=actual,
            output_hash=output_hash(actual),
        )
        was_fixed = case["fixed_in_version_id"] is not None
        if passed:
            if not was_fixed:
                db.set_case_fixed_in(conn, case["id"], version["id"])
                newly_fixed.append(case)
        elif was_fixed:
            regressions.append(case)
        else:
            still_failing.append(case)

    return {
        "checked": len(cases),
        "regressions": regressions,
        "still_failing": still_failing,
        "newly_fixed": newly_fixed,
        "verdict": "BLOCK" if regressions else "PASS",
    }
