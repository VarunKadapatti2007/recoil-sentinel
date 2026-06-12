"""Suite runner: execute + judge a candidate version against eval cases.

Caching contract (the demo-determinism mechanism):
- Every verdict is cached in eval_results keyed (eval_case_id,
  agent_version_id, output_hash).
- In RECOIL_DEMO_MODE the runner reads the cache first and only invokes the
  agent/judge on a true miss, so the scripted demo path is fully cached and
  network-free. Outside demo mode, judging is live.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Iterator, Optional

from .. import config, db
from ..agent import run_agent
from ..judge import get_judge, output_hash
from ..models import JudgeVerdict


def judge_case(
    conn: sqlite3.Connection,
    case: dict[str, Any],
    version: dict[str, Any],
    *,
    use_cache: Optional[bool] = None,
    live_agent: bool = False,
) -> dict[str, Any]:
    """Evaluate one case for one version. Returns the eval_result dict."""
    use_cache = config.DEMO_MODE if use_cache is None else use_cache

    if use_cache:
        cached = db.get_cached_result(conn, case["id"], version["id"])
        if cached is not None:
            cached["from_cache"] = True
            return cached

    trace = run_agent(version, case["input"], live=live_agent, seed=_seed_for(case, version))
    out = trace["output"]
    ohash = output_hash(out)

    cached = db.get_cached_result(conn, case["id"], version["id"], ohash)
    if cached is not None:
        cached["from_cache"] = True
        return cached

    judge = get_judge()
    verdict: JudgeVerdict = judge.evaluate(
        input=case["input"],
        output=out,
        rubric=case["rubric"],
        reference_behavior=case["reference_behavior"],
        ground_truth=case.get("context_snapshot"),
    )
    rid = db.upsert_eval_result(
        conn,
        eval_case_id=case["id"],
        agent_version_id=version["id"],
        passed=verdict.passed,
        score=verdict.score,
        judge_rationale=verdict.rationale,
        actual_output=out,
        output_hash=ohash,
        from_cache=False,
    )
    if verdict.passed:
        db.set_case_fixed_in(conn, case["id"], version["id"])
    result = db.get_cached_result(conn, case["id"], version["id"], ohash)
    assert result is not None, rid
    return result


def run_suite_for_version(
    conn: sqlite3.Connection,
    version: dict[str, Any],
    *,
    use_cache: Optional[bool] = None,
    live_agent: bool = False,
    on_case: Optional[Callable[[dict[str, Any], dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """Run every active case for a version; returns the list of eval_results.
    on_case(case, result) fires after each case (used by SSE streaming)."""
    results = []
    for case in db.list_eval_cases(conn, status="active"):
        result = judge_case(
            conn, case, version, use_cache=use_cache, live_agent=live_agent
        )
        results.append(result)
        if on_case is not None:
            on_case(case, result)
    return results


def iter_suite_for_version(
    conn: sqlite3.Connection,
    version: dict[str, Any],
    *,
    use_cache: Optional[bool] = None,
    live_agent: bool = False,
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Generator variant for streaming: yields (case, result) pairs."""
    for case in db.list_eval_cases(conn, status="active"):
        yield case, judge_case(conn, case, version, use_cache=use_cache, live_agent=live_agent)


def _seed_for(case: dict[str, Any], version: dict[str, Any]) -> int:
    return abs(hash((case["id"], version["id"]))) % (2**31)
