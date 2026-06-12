"""THE core: regression detection + verdict + exit codes.

classify_cases() is a pure function over (cases, baseline results, candidate
results) so the regression logic is directly unit-testable:

- regression   = baseline passed AND candidate failed  -> BLOCK
- newly_fixed  = baseline failed AND candidate passed  -> counted, not blocking
- still_passing / still_failing / new_case             -> not blocking

Verdict = BLOCK iff any regression exists, else PASS.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Optional

from .. import db
from ..evals.runner import run_suite_for_version
from ..models import CaseClassification, GateReport


class GateError(Exception):
    pass


def classify_cases(
    cases: list[dict[str, Any]],
    baseline_results: dict[str, bool | None],
    candidate_results: dict[str, bool],
) -> list[CaseClassification]:
    """Classify each case by (baseline_passed, candidate_passed).

    baseline_results maps case_id -> passed (None/absent = no baseline result,
    i.e. a case newer than the baseline). candidate_results maps case_id ->
    passed and must cover every case.
    """
    classifications: list[CaseClassification] = []
    for case in cases:
        cid = case["id"]
        if cid not in candidate_results:
            raise GateError(f"candidate has no result for case {cid!r}")
        cand = candidate_results[cid]
        base = baseline_results.get(cid)
        if base is True and not cand:
            kind = "regression"
        elif base is False and cand:
            kind = "newly_fixed"
        elif base is None:
            kind = "new_case"
        elif cand:
            kind = "still_passing"
        else:
            kind = "still_failing"
        classifications.append(
            CaseClassification(
                eval_case_id=cid,
                title=case["title"],
                severity=case["severity"],
                baseline_passed=base,
                candidate_passed=cand,
                kind=kind,
            )
        )
    return classifications


def verdict_for(classifications: list[CaseClassification]) -> str:
    return "BLOCK" if any(c.kind == "regression" for c in classifications) else "PASS"


def run_gate(
    conn: sqlite3.Connection,
    *,
    candidate: str,
    baseline: Optional[str] = None,
    use_cache: Optional[bool] = None,
    live_agent: bool = False,
    persist: bool = True,
    on_case: Optional[Callable[[dict[str, Any], dict[str, Any]], None]] = None,
) -> GateReport:
    """Resolve versions, run the candidate against every active case, classify
    against the baseline's latest results, persist a gate_runs row, return report.
    """
    cand_v = db.resolve_version(conn, candidate)
    if cand_v is None:
        raise GateError(f"candidate version {candidate!r} not found")

    if baseline:
        base_v = db.resolve_version(conn, baseline)
        if base_v is None:
            raise GateError(f"baseline version {baseline!r} not found")
    else:
        base_v = db.get_published_version(conn)
        if base_v is None:
            raise GateError("no published baseline version exists; pass --baseline explicitly")

    cases = db.list_eval_cases(conn, status="active")

    # Candidate: run (or read cached) results for every active case.
    cand_results_list = run_suite_for_version(
        conn, cand_v, use_cache=use_cache, live_agent=live_agent, on_case=on_case
    )
    cand_results = {r["eval_case_id"]: r["passed"] for r in cand_results_list}

    # Baseline: latest persisted result per case (never re-run on the gate path).
    base_results: dict[str, bool | None] = {
        r["eval_case_id"]: r["passed"] for r in db.list_results_for_version(conn, base_v["id"])
    }

    classifications = classify_cases(cases, base_results, cand_results)
    verdict = verdict_for(classifications)
    regressed = [c.eval_case_id for c in classifications if c.kind == "regression"]
    newly_fixed = [c.eval_case_id for c in classifications if c.kind == "newly_fixed"]
    passed_count = sum(1 for c in classifications if c.candidate_passed)
    failed_count = len(classifications) - passed_count

    gate_run_id = None
    if persist:
        gate_run_id = db.insert_gate_run(
            conn,
            candidate_version_id=cand_v["id"],
            baseline_version_id=base_v["id"],
            total_cases=len(classifications),
            passed_count=passed_count,
            failed_count=failed_count,
            regressed_case_ids=regressed,
            newly_fixed_case_ids=newly_fixed,
            verdict=verdict,
        )

    return GateReport(
        candidate_version_id=cand_v["id"],
        candidate_label=cand_v["label"],
        baseline_version_id=base_v["id"],
        baseline_label=base_v["label"],
        cases=classifications,
        verdict=verdict,  # type: ignore[arg-type]
        total_cases=len(classifications),
        passed_count=passed_count,
        failed_count=failed_count,
        regressed_case_ids=regressed,
        newly_fixed_case_ids=newly_fixed,
        gate_run_id=gate_run_id,
    )
