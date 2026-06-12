"""Trace capture: persist an agent execution as an OpenTelemetry-style run row."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .. import db


def capture_run(
    conn: sqlite3.Connection,
    *,
    agent_version_id: str,
    input: dict[str, Any],
    trace: dict[str, Any],
    created_at: Optional[str] = None,
) -> str:
    """Persist the result of agent.run_agent() as a runs row. Returns run id."""
    return db.insert_run(
        conn,
        agent_version_id=agent_version_id,
        input=input,
        output=trace["output"],
        spans=trace["spans"],
        ground_truth_ref=trace.get("ground_truth_ref"),
        latency_ms=trace["latency_ms"],
        total_cost_usd=trace["total_cost_usd"],
        created_at=created_at,
    )
