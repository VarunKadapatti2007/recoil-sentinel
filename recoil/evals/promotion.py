"""turns failures into frozen eval cases — the suite grows itself.

when a run fails, we freeze it into a permanent regression case: input +
ground-truth snapshot + the judge's reference behavior, tagged with
first_failed_version_id. when a later version passes it, fixed_in_version_id
gets stamped (see runner.py).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .. import db
from ..models import JudgeVerdict


def _default_rubric(input: dict[str, Any]) -> str:
    return (
        "The agent's structured triage decision (queue, priority, escalate, on_call_paged) "
        "must match the captured ground truth for this incident, and the reason field must "
        "be free of customer PII. Grade against the context snapshot, not priors."
    )


def promote_failure_to_case(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    verdict: JudgeVerdict,
    title: Optional[str] = None,
    severity: str = "medium",
    rubric: Optional[str] = None,
) -> Optional[str]:
    """freeze a failed run into an eval case. returns the new case id, or None
    if a case with the same input already exists."""
    run = db.get_run(conn, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    # idempotent: if the same input is already frozen, skip
    import json

    input_json = json.dumps(run["input"], sort_keys=True)
    existing = conn.execute(
        "SELECT id FROM eval_cases WHERE input_json = ?", (input_json,)
    ).fetchone()
    if existing:
        return None

    context_snapshot = {
        "expected": run["input"].get("_expected", {}),
        "constraints": run["input"].get("_constraints", {}),
        "ground_truth_source": run.get("ground_truth_ref") or "mock://incident-history",
        "captured_output": run["output"],
        "captured_at": run["created_at"],
    }
    case_input = {k: v for k, v in run["input"].items() if not k.startswith("_")}

    return db.insert_eval_case(
        conn,
        source_run_id=run_id,
        title=title or _auto_title(case_input),
        input=case_input,
        context_snapshot=context_snapshot,
        rubric=rubric or _default_rubric(case_input),
        reference_behavior=verdict.reference_output
        or "Match the captured ground-truth triage decision.",
        severity=severity,
        first_failed_version_id=run["agent_version_id"],
    )


def _auto_title(input: dict[str, Any]) -> str:
    title = input.get("title") or input.get("message") or "Untitled incident"
    return (title[:77] + "...") if len(title) > 80 else title
