"""Recoil API server: read APIs for the dashboard + SSE gate streaming.

Defensive by design: clean 404s on missing records, never a raw 500 on the
demo path. CORS pinned to the local web origin.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from recoil import config, db
from recoil.gate.engine import classify_cases, verdict_for, GateError

app = FastAPI(title="Recoil API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.WEB_ORIGIN, "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# x402 paywall (Phase E): the premium report endpoint is monetized via the
# Coinbase HTTP-402 standard. Activates only when a wallet is configured AND
# the x402 SDK is installed; otherwise the endpoint stays open with a notice.
# Testnet (base-sepolia) uses the public facilitator at x402.org.
# ---------------------------------------------------------------------------
X402_ACTIVE = False
if config.X402_WALLET_ADDRESS:
    try:
        from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.server import x402ResourceServer

        _NETWORKS = {"base-sepolia": "eip155:84532", "base": "eip155:8453"}
        _x402_network = _NETWORKS.get(config.X402_NETWORK, config.X402_NETWORK)
        _facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=config.X402_FACILITATOR_URL))
        _x402_server = x402ResourceServer(_facilitator)
        _x402_server.register(_x402_network, ExactEvmServerScheme())
        app.add_middleware(
            PaymentMiddlewareASGI,
            routes={
                "GET /api/sentinel/premium": RouteConfig(
                    accepts=[
                        PaymentOption(
                            scheme="exact",
                            pay_to=config.X402_WALLET_ADDRESS,
                            price=config.X402_PRICE,
                            network=_x402_network,
                        )
                    ],
                    mime_type="application/json",
                    description="Recoil Sentinel premium intel report (machine-verified claims)",
                )
            },
            server=_x402_server,
        )
        X402_ACTIVE = True
    except Exception as _exc:  # paywall must never take the API down
        import logging as _logging

        _logging.getLogger("recoil.server").warning("x402 paywall disabled: %s", _exc)


def _conn() -> sqlite3.Connection:
    conn = db.connect()
    db.init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Built-in autonomy scheduler (Phase G): when RECOIL_SENTINEL_INTERVAL_S is
# set (e.g. 21600 = 6h on Render), the API process itself runs the full
# sentinel cycle on a timer — one service, no cron, no human in the loop.
# ---------------------------------------------------------------------------
import logging
import os
import threading

_sched_log = logging.getLogger("recoil.scheduler")


def _sentinel_loop(interval_s: int) -> None:
    from recoil.cli import _sentinel_once

    while True:
        try:
            code = _sentinel_once(out=None, skip_gate=False)
            _sched_log.info("scheduled sentinel run finished with exit %s", code)
        except Exception as exc:  # the scheduler must survive anything
            _sched_log.error("scheduled sentinel run crashed: %s", exc)
        threading.Event().wait(interval_s)


@app.on_event("startup")
def _start_sentinel_scheduler() -> None:
    raw = os.environ.get("RECOIL_SENTINEL_INTERVAL_S", "").strip()
    if not raw:
        return
    try:
        interval_s = max(int(raw), 300)
    except ValueError:
        _sched_log.error("invalid RECOIL_SENTINEL_INTERVAL_S=%r — scheduler disabled", raw)
        return
    threading.Thread(
        target=_sentinel_loop, args=(interval_s,), daemon=True, name="sentinel-scheduler"
    ).start()
    _sched_log.info("sentinel scheduler started: every %ss (first run now)", interval_s)


def _label_map(conn: sqlite3.Connection) -> dict[str, str]:
    return {v["id"]: v["label"] for v in db.list_versions(conn)}


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------

@app.get("/api/overview")
def overview() -> dict[str, Any]:
    conn = _conn()
    try:
        cases = db.list_eval_cases(conn, status="active")
        published = db.get_published_version(conn)
        labels = _label_map(conn)

        pass_rate = None
        version_rates = []
        for v in db.list_versions(conn):
            results = db.list_results_for_version(conn, v["id"])
            if results:
                rate = sum(1 for r in results if r["passed"]) / len(results)
                version_rates.append(
                    {"label": v["label"], "pass_rate": round(rate, 3), "results": len(results)}
                )
                if published and v["id"] == published["id"]:
                    pass_rate = round(rate, 3)

        gate_runs = db.list_gate_runs(conn, limit=8)
        for g in gate_runs:
            g["candidate_label"] = labels.get(g["candidate_version_id"], "?")
            g["baseline_label"] = labels.get(g["baseline_version_id"], "?")

        recent = db.list_runs(conn, limit=120)
        runs_today = [r for r in recent]
        latencies = sorted(r["latency_ms"] for r in runs_today) or [0]
        p95 = latencies[int(len(latencies) * 0.95) - 1] if len(latencies) > 1 else latencies[0]

        # pass-rate-over-time sparkline: chronological per-version suite rates
        return {
            "total_runs": db.count_runs(conn),
            "total_cases": len(cases),
            "critical_cases": sum(1 for c in cases if c["severity"] == "critical"),
            "suite_pass_rate": pass_rate,
            "published_version": published["label"] if published else None,
            "last_gate": gate_runs[0] if gate_runs else None,
            "gate_runs": gate_runs,
            "version_pass_rates": version_rates,
            "p95_latency_ms": round(p95, 1),
            "avg_cost_usd": round(
                sum(r["total_cost_usd"] for r in runs_today) / max(len(runs_today), 1), 6
            ),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------

@app.get("/api/versions")
def versions() -> list[dict[str, Any]]:
    conn = _conn()
    try:
        out = []
        for v in db.list_versions(conn):
            results = db.list_results_for_version(conn, v["id"])
            out.append(
                {
                    **{k: v[k] for k in ("id", "label", "model", "is_published", "created_at", "parent_version_id")},
                    "system_prompt": v["system_prompt"],
                    "suite_results": len(results),
                    "suite_passed": sum(1 for r in results if r["passed"]),
                }
            )
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# runs / traces
# ---------------------------------------------------------------------------

@app.get("/api/runs")
def runs(limit: int = Query(50, le=200), offset: int = 0) -> dict[str, Any]:
    conn = _conn()
    try:
        labels = _label_map(conn)
        items = db.list_runs(conn, limit=limit, offset=offset)
        for r in items:
            r["version_label"] = labels.get(r["agent_version_id"], "?")
            r["span_count"] = len(r["spans"])
            del r["spans"]  # list view stays light
        return {"items": items, "total": db.count_runs(conn)}
    finally:
        conn.close()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        run["version_label"] = _label_map(conn).get(run["agent_version_id"], "?")
        return run
    finally:
        conn.close()


class TestAlertRequest(BaseModel):
    version_label: str = Field(default="v_good")
    input: dict[str, Any]


@app.post("/api/runs")
def send_test_alert(req: TestAlertRequest) -> dict[str, Any]:
    """'Send test alert': fire a real agent run, capture the trace, judge it,
    and (on FAIL) promote it into the suite — the capture->judge->freeze loop."""
    conn = _conn()
    try:
        version = db.resolve_version(conn, req.version_label)
        if version is None:
            raise HTTPException(status_code=404, detail=f"version {req.version_label!r} not found")

        from recoil.agent import run_agent
        from recoil.evals.promotion import promote_failure_to_case
        from recoil.judge import get_judge
        from recoil.tracing import capture_run

        trace = run_agent(version, req.input, live=True)
        run_id = capture_run(conn, agent_version_id=version["id"], input=req.input, trace=trace)

        ground_truth = {
            "expected": req.input.get("_expected", {}),
            "constraints": req.input.get("_constraints", {"must_not_contain_pii": True}),
            "ground_truth_source": req.input.get("ground_truth_ref", "operator-supplied"),
        }
        verdict = get_judge().evaluate(
            input=req.input,
            output=trace["output"],
            rubric="Triage decision must match operator ground truth where provided; reason must be PII-free.",
            reference_behavior="Match the operator-recorded correct triage decision.",
            ground_truth=ground_truth,
        )
        promoted_case_id = None
        if not verdict.passed:
            promoted_case_id = promote_failure_to_case(conn, run_id=run_id, verdict=verdict)
        return {
            "run_id": run_id,
            "output": trace["output"],
            "latency_ms": trace["latency_ms"],
            "judge_passed": verdict.passed,
            "judge_rationale": verdict.rationale,
            "promoted_case_id": promoted_case_id,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# eval cases
# ---------------------------------------------------------------------------

@app.get("/api/eval-cases")
def eval_cases() -> list[dict[str, Any]]:
    conn = _conn()
    try:
        labels = _label_map(conn)
        out = []
        for c in db.list_eval_cases(conn):
            results = db.list_results_for_case(conn, c["id"])
            c["first_failed_label"] = labels.get(c["first_failed_version_id"] or "", None)
            c["fixed_in_label"] = labels.get(c["fixed_in_version_id"] or "", None)
            c["ground_truth_source"] = c["context_snapshot"].get("ground_truth_source")
            c["result_count"] = len(results)
            out.append(c)
        return out
    finally:
        conn.close()


@app.get("/api/eval-cases/{case_id}")
def eval_case_detail(case_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        case = db.get_eval_case(conn, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="eval case not found")
        labels = _label_map(conn)
        results = db.list_results_for_case(conn, case_id)
        for r in results:
            r["version_label"] = labels.get(r["agent_version_id"], "?")
        case["first_failed_label"] = labels.get(case["first_failed_version_id"] or "", None)
        case["fixed_in_label"] = labels.get(case["fixed_in_version_id"] or "", None)
        case["results"] = results
        return case
    finally:
        conn.close()


@app.get("/api/eval-cases/{case_id}/diff")
def case_diff(
    case_id: str,
    baseline: str = Query(...),
    candidate: str = Query(...),
) -> dict[str, Any]:
    """Field-by-field semantic diff of structured outputs for the hero screen."""
    conn = _conn()
    try:
        case = db.get_eval_case(conn, case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="eval case not found")
        base_v = db.resolve_version(conn, baseline)
        cand_v = db.resolve_version(conn, candidate)
        if base_v is None or cand_v is None:
            raise HTTPException(status_code=404, detail="version not found")
        base_r = db.get_cached_result(conn, case_id, base_v["id"])
        cand_r = db.get_cached_result(conn, case_id, cand_v["id"])
        if base_r is None or cand_r is None:
            raise HTTPException(
                status_code=404, detail="no judged result for one of the versions on this case"
            )
        fields = ["queue", "priority", "escalate", "on_call_paged", "reason"]
        diff = []
        for f in fields:
            b, c = base_r["actual_output"].get(f), cand_r["actual_output"].get(f)
            diff.append({"field": f, "baseline": b, "candidate": c, "changed": b != c})
        return {
            "case": {k: case[k] for k in ("id", "title", "severity", "rubric", "reference_behavior", "input", "context_snapshot")},
            "baseline": {"label": base_v["label"], "passed": base_r["passed"], "rationale": base_r["judge_rationale"]},
            "candidate": {"label": cand_v["label"], "passed": cand_r["passed"], "rationale": cand_r["judge_rationale"]},
            "fields": diff,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

@app.get("/api/gate-runs")
def gate_runs(limit: int = Query(20, le=100)) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        labels = _label_map(conn)
        items = db.list_gate_runs(conn, limit=limit)
        for g in items:
            g["candidate_label"] = labels.get(g["candidate_version_id"], "?")
            g["baseline_label"] = labels.get(g["baseline_version_id"], "?")
        return items
    finally:
        conn.close()


class PublishRequest(BaseModel):
    candidate: str


@app.post("/api/publish")
def publish(req: PublishRequest) -> dict[str, Any]:
    conn = _conn()
    try:
        from recoil.adapters import get_publish_target
        from recoil.gate import run_gate

        try:
            report = run_gate(conn, candidate=req.candidate)
        except GateError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        published = False
        if report.verdict == "PASS":
            get_publish_target().publish(conn, report.candidate_version_id)
            published = True
        return {"verdict": report.verdict, "published": published, "report": report.model_dump()}
    finally:
        conn.close()


@app.get("/api/gate/stream")
async def gate_stream(
    candidate: str = Query(...),
    baseline: Optional[str] = Query(None),
    publish: bool = Query(False),
    case_delay_ms: int = Query(420, ge=0, le=2000),
) -> StreamingResponse:
    """SSE stream of a gate run, case by case, then the final verdict.

    Events:
      start    {candidate, baseline, total_cases}
      case     {index, case_id, title, severity, baseline_passed, candidate_passed, kind, ...}
      verdict  {verdict, passed_count, failed_count, regressed, newly_fixed, published, gate_run_id}
      error    {message}
    """

    async def event_source():
        conn = _conn()
        try:
            cand_v = db.resolve_version(conn, candidate)
            if cand_v is None:
                yield _sse("error", {"message": f"candidate {candidate!r} not found"})
                return
            base_v = (
                db.resolve_version(conn, baseline) if baseline else db.get_published_version(conn)
            )
            if base_v is None:
                yield _sse("error", {"message": "no baseline version available"})
                return

            cases = db.list_eval_cases(conn, status="active")
            yield _sse(
                "start",
                {
                    "candidate": cand_v["label"],
                    "baseline": base_v["label"],
                    "total_cases": len(cases),
                },
            )

            from recoil.evals.runner import judge_case

            base_results = {
                r["eval_case_id"]: r["passed"]
                for r in db.list_results_for_version(conn, base_v["id"])
            }
            cand_results: dict[str, bool] = {}
            for i, case in enumerate(cases):
                # legible pacing for the live audience; cached verdicts resolve instantly otherwise
                if case_delay_ms:
                    await asyncio.sleep(case_delay_ms / 1000)
                result = await asyncio.to_thread(judge_case, conn, case, cand_v)
                cand_results[case["id"]] = result["passed"]
                base = base_results.get(case["id"])
                kind = (
                    "regression"
                    if base is True and not result["passed"]
                    else "newly_fixed"
                    if base is False and result["passed"]
                    else "new_case"
                    if base is None
                    else "still_passing"
                    if result["passed"]
                    else "still_failing"
                )
                yield _sse(
                    "case",
                    {
                        "index": i,
                        "case_id": case["id"],
                        "title": case["title"],
                        "severity": case["severity"],
                        "baseline_passed": base,
                        "candidate_passed": result["passed"],
                        "score": result["score"],
                        "rationale": result["judge_rationale"],
                        "from_cache": result["from_cache"],
                        "kind": kind,
                    },
                )

            classifications = classify_cases(cases, base_results, cand_results)
            verdict = verdict_for(classifications)
            regressed = [c.eval_case_id for c in classifications if c.kind == "regression"]
            newly_fixed = [c.eval_case_id for c in classifications if c.kind == "newly_fixed"]
            passed_count = sum(1 for c in classifications if c.candidate_passed)
            gate_run_id = db.insert_gate_run(
                conn,
                candidate_version_id=cand_v["id"],
                baseline_version_id=base_v["id"],
                total_cases=len(classifications),
                passed_count=passed_count,
                failed_count=len(classifications) - passed_count,
                regressed_case_ids=regressed,
                newly_fixed_case_ids=newly_fixed,
                verdict=verdict,
            )
            published = False
            if publish and verdict == "PASS":
                from recoil.adapters import get_publish_target

                get_publish_target().publish(conn, cand_v["id"])
                published = True
            yield _sse(
                "verdict",
                {
                    "verdict": verdict,
                    "passed_count": passed_count,
                    "failed_count": len(classifications) - passed_count,
                    "total_cases": len(classifications),
                    "regressed": regressed,
                    "newly_fixed": newly_fixed,
                    "published": published,
                    "publish_attempted": publish,
                    "gate_run_id": gate_run_id,
                },
            )
        except Exception as exc:  # never let a raw exception reach the stream
            yield _sse("error", {"message": f"gate stream failed: {exc}"})
        finally:
            conn.close()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# voice
# ---------------------------------------------------------------------------

@app.get("/api/voice/{verdict}")
def voice(verdict: str) -> FileResponse:
    from recoil.voice import verdict_audio_path

    v = verdict.upper()
    if v not in ("PASS", "BLOCK"):
        raise HTTPException(status_code=404, detail="unknown verdict")
    path = verdict_audio_path(v)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no pre-rendered audio for this verdict")
    return FileResponse(path, media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# sentinel (the autonomous publisher)
# ---------------------------------------------------------------------------

@app.get("/cited.md")
def cited_md():
    """The agent's published output — the public artifact."""
    from recoil.sentinel.publish import CITED_MD_PATH

    if not CITED_MD_PATH.exists():
        raise HTTPException(status_code=404, detail="no report published yet")
    return FileResponse(CITED_MD_PATH, media_type="text/markdown; charset=utf-8")


@app.get("/api/sentinel/latest")
def sentinel_latest() -> dict[str, Any]:
    """Machine-readable sidecar of the latest published report."""
    from recoil.sentinel.publish import CITED_MD_PATH

    sidecar = CITED_MD_PATH.with_suffix(".json")
    if not sidecar.exists():
        raise HTTPException(status_code=404, detail="no report published yet")
    return json.loads(sidecar.read_text(encoding="utf-8"))


@app.get("/api/sentinel/premium")
def sentinel_premium() -> dict[str, Any]:
    """Premium intel: full report + per-claim verification evidence.
    Behind the x402 paywall when configured — an agent (or human) must pay
    {X402_PRICE} in USDC on {X402_NETWORK} to unlock."""
    from recoil.sentinel.publish import CITED_MD_PATH

    sidecar = CITED_MD_PATH.with_suffix(".json")
    if not sidecar.exists():
        raise HTTPException(status_code=404, detail="no report published yet")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    return {
        "tier": "premium",
        "paywalled": X402_ACTIVE,
        "report": payload["report"],
        "verification_evidence": payload["verification"],
        "ground_truth_snapshot": payload["snapshot"],
        "llm": payload["llm"],
        "run_id": payload["run_id"],
    }


@app.get("/api/sentinel/status")
def sentinel_status() -> dict[str, Any]:
    from recoil.sentinel.gate import list_sentinel_cases
    from recoil.sentinel.integrations import clickhouse_stats
    from recoil.sentinel.publish import CITED_MD_PATH, SENTINEL_VERSION_LABEL

    conn = _conn()
    try:
        version = db.get_version_by_label(conn, SENTINEL_VERSION_LABEL)
        runs = []
        if version:
            rows = conn.execute(
                "SELECT id, latency_ms, total_cost_usd, created_at FROM runs "
                "WHERE agent_version_id = ? ORDER BY created_at DESC LIMIT 20",
                (version["id"],),
            ).fetchall()
            runs = [dict(r) for r in rows]
        return {
            "published": CITED_MD_PATH.exists(),
            "frozen_failure_cases": len(list_sentinel_cases(conn)),
            "recent_runs": runs,
            "paywall_active": X402_ACTIVE,
            "clickhouse": clickhouse_stats(),
        }
    finally:
        conn.close()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "demo_mode": config.DEMO_MODE, "ts": time.time()}
