"""publisher: render the verified report to cited.md (+ json sidecar) and
capture the whole run as a recoil trace.

gate rule (the recoil dna): we refuse to publish unless every claim verified
against the live snapshot. a blocked report still gets recorded — failures are
data — but cited.md never gets written with one.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import config, db
from ..models import Span
from ..tracing import capture_run
from .agent import IntelReport, VerificationResult

import os

# overridable so a deployed cron (writing to shared disk) and the api server
# agree on one path; defaults to repo root for local dev.
CITED_MD_PATH = Path(os.environ.get("RECOIL_CITED_PATH", config.REPO_ROOT / "cited.md"))

SENTINEL_VERSION_LABEL = "sentinel_v1"
SENTINEL_SYSTEM_NOTE = (
    "Recoil Sentinel: autonomous crypto intel agent. Reports are grounded in live "
    "CoinGecko/DefiLlama snapshots and gated by claim-level verification."
)

_SIGNAL_MARK = {"bullish": "▲", "bearish": "▼", "neutral": "•", "risk": "⚠"}


def _ensure_sentinel_version(conn: sqlite3.Connection) -> dict[str, Any]:
    version = db.get_version_by_label(conn, SENTINEL_VERSION_LABEL)
    if version is None:
        db.insert_agent_version(
            conn,
            label=SENTINEL_VERSION_LABEL,
            system_prompt=SENTINEL_SYSTEM_NOTE,
            model=config.AGENT_MODEL,
            params={"max_tokens": 2500},
            is_published=False,
        )
        version = db.get_version_by_label(conn, SENTINEL_VERSION_LABEL)
    assert version is not None
    return version


def render_cited_md(
    report: IntelReport,
    snapshot: dict[str, Any],
    verification: VerificationResult,
    *,
    run_id: str,
) -> str:
    """render the report with deterministic, resolvable citations."""
    metrics = snapshot["metrics"]

    # number citations by first appearance over every metric actually used
    cited_keys: list[str] = []
    for f in report.findings:
        for k in f.metric_keys:
            if k in metrics and k not in cited_keys:
                cited_keys.append(k)
    cite_no = {k: i + 1 for i, k in enumerate(cited_keys)}

    lines: list[str] = []
    lines.append(f"# {report.title}")
    lines.append("")
    lines.append(
        f"> **Recoil Sentinel** · autonomous intelligence brief · generated "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"run `{run_id[:8]}` · confidence: **{report.confidence}**"
    )
    lines.append(
        f"> Ground truth: live snapshot at {snapshot['fetched_at']} · "
        f"**{sum(1 for c in verification.checks if c.ok)}/{len(verification.checks)} claims verified** "
        "against source data before publication."
    )
    lines.append("")
    lines.append("## Executive summary")
    lines.append("")
    lines.append(report.executive_summary)
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    for f in report.findings:
        refs = "".join(f"[^{cite_no[k]}]" for k in f.metric_keys if k in cite_no)
        lines.append(f"### {_SIGNAL_MARK.get(f.signal, '•')} {f.headline}")
        lines.append("")
        lines.append(f"{f.body} {refs}".rstrip())
        lines.append("")
    if report.risk_flags:
        lines.append("## Risk flags")
        lines.append("")
        for r in report.risk_flags:
            lines.append(f"- {r}")
        lines.append("")
    lines.append("## Citations")
    lines.append("")
    for k in cited_keys:
        m = metrics[k]
        value = m["value"]
        display = f"{value:,.2f}" if isinstance(value, float) else str(value)
        lines.append(
            f"[^{cite_no[k]}]: **{m['label']}** = {display} ({m['unit']}) — "
            f"{m['source']}, fetched {snapshot['fetched_at']} — <{m['source_url']}>"
        )
    lines.append("")
    lines.append("---")
    lines.append(
        "*Published autonomously by [Recoil Sentinel](https://github.com/) — every numeric "
        "claim is machine-verified against its cited source before this file is written. "
        "A failed verification blocks publication (exit 1).*"
    )
    lines.append("")
    return "\n".join(lines)


def publish_report(
    conn: sqlite3.Connection,
    *,
    report: IntelReport,
    snapshot: dict[str, Any],
    verification: VerificationResult,
    llm_stats: dict[str, Any],
    fetch_ms: float,
    out_path: Optional[Path] = None,
) -> dict[str, Any]:
    """capture the trace; only write cited.md if verification passed.
    returns {run_id, published, path, verdict}."""
    version = _ensure_sentinel_version(conn)

    t = 0.0
    spans = [
        Span(
            name="ground_truth.fetch_live_snapshot",
            type="tool",
            start_ms=t,
            end_ms=t + fetch_ms,
            attributes={
                "sources": ["CoinGecko", "DefiLlama"],
                "metrics": len(snapshot["metrics"]),
                "errors": snapshot.get("source_errors", []),
            },
        )
    ]
    t += fetch_ms
    spans.append(
        Span(
            name="llm.generate_intel_report",
            type="llm",
            start_ms=t,
            end_ms=t + llm_stats["latency_ms"],
            model=llm_stats["model"],
            prompt_tokens=llm_stats["prompt_tokens"],
            completion_tokens=llm_stats["completion_tokens"],
            cost_usd=llm_stats["cost_usd"],
            attributes={"live": True},
        )
    )
    t += llm_stats["latency_ms"]
    spans.append(
        Span(
            name="gate.verify_claims",
            type="tool",
            start_ms=t,
            end_ms=t + 5,
            attributes={
                "checks": len(verification.checks),
                "passed": verification.passed,
                "problems": verification.problems,
            },
        )
    )

    run_id = capture_run(
        conn,
        agent_version_id=version["id"],
        input={
            "kind": "sentinel_intel",
            "title": report.title,
            "snapshot_fetched_at": snapshot["fetched_at"],
            "metric_keys": sorted(snapshot["metrics"].keys()),
        },
        trace={
            "output": {
                "report": report.model_dump(),
                "verification": verification.model_dump(),
            },
            "spans": [s.model_dump() for s in spans],
            "latency_ms": round(t + 5, 1),
            "total_cost_usd": llm_stats["cost_usd"],
            "ground_truth_ref": "live://coingecko+defillama",
        },
    )

    path = out_path or CITED_MD_PATH
    if verification.passed:
        path.write_text(
            render_cited_md(report, snapshot, verification, run_id=run_id),
            encoding="utf-8",
        )
        sidecar = path.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "report": report.model_dump(),
                    "snapshot": snapshot,
                    "verification": verification.model_dump(),
                    "llm": llm_stats,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return {"run_id": run_id, "published": True, "path": str(path), "verdict": "PASS"}

    return {
        "run_id": run_id,
        "published": False,
        "path": None,
        "verdict": "BLOCK",
        "problems": verification.problems,
    }
