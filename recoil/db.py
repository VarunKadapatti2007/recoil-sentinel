"""Thin SQLite data-access layer. Deliberately boring: stdlib sqlite3, explicit
SQL, dict rows, no ORM. Reliability over cleverness on the demo path.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_versions (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    system_prompt TEXT NOT NULL,
    model TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    parent_version_id TEXT REFERENCES agent_versions(id),
    is_published INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    agent_version_id TEXT NOT NULL REFERENCES agent_versions(id),
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    spans_json TEXT NOT NULL DEFAULT '[]',
    ground_truth_ref TEXT,
    latency_ms REAL NOT NULL,
    total_cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_version ON runs(agent_version_id);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);

CREATE TABLE IF NOT EXISTS eval_cases (
    id TEXT PRIMARY KEY,
    source_run_id TEXT REFERENCES runs(id),
    title TEXT NOT NULL,
    input_json TEXT NOT NULL,
    context_snapshot_json TEXT NOT NULL DEFAULT '{}',
    rubric TEXT NOT NULL,
    reference_behavior TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'active',
    first_failed_version_id TEXT REFERENCES agent_versions(id),
    fixed_in_version_id TEXT REFERENCES agent_versions(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON eval_cases(status);

CREATE TABLE IF NOT EXISTS eval_results (
    id TEXT PRIMARY KEY,
    eval_case_id TEXT NOT NULL REFERENCES eval_cases(id),
    agent_version_id TEXT NOT NULL REFERENCES agent_versions(id),
    passed INTEGER NOT NULL,
    score REAL NOT NULL,
    judge_rationale TEXT NOT NULL,
    actual_output_json TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    from_cache INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (eval_case_id, agent_version_id, output_hash)
);
CREATE INDEX IF NOT EXISTS idx_results_case ON eval_results(eval_case_id);
CREATE INDEX IF NOT EXISTS idx_results_version ON eval_results(agent_version_id);

CREATE TABLE IF NOT EXISTS gate_runs (
    id TEXT PRIMARY KEY,
    candidate_version_id TEXT NOT NULL REFERENCES agent_versions(id),
    baseline_version_id TEXT NOT NULL REFERENCES agent_versions(id),
    total_cases INTEGER NOT NULL,
    passed_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    regressed_case_ids_json TEXT NOT NULL DEFAULT '[]',
    newly_fixed_case_ids_json TEXT NOT NULL DEFAULT '[]',
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gate_created ON gate_runs(created_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the SSE stream judges cases via asyncio.to_thread;
    # access is strictly sequential per connection, never concurrent.
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def reset_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Drop everything and recreate the schema. Used by `recoil reset --demo`."""
    conn = connect(db_path)
    conn.executescript(
        """
        DROP TABLE IF EXISTS gate_runs;
        DROP TABLE IF EXISTS eval_results;
        DROP TABLE IF EXISTS eval_cases;
        DROP TABLE IF EXISTS runs;
        DROP TABLE IF EXISTS agent_versions;
        """
    )
    init_db(conn)
    return conn


# --------------------------------------------------------------------------
# agent_versions
# --------------------------------------------------------------------------

def insert_agent_version(
    conn: sqlite3.Connection,
    *,
    label: str,
    system_prompt: str,
    model: str,
    params: Optional[dict[str, Any]] = None,
    parent_version_id: Optional[str] = None,
    is_published: bool = False,
    created_at: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    vid = id or new_id()
    conn.execute(
        """INSERT INTO agent_versions
           (id, label, system_prompt, model, params_json, parent_version_id, is_published, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            vid,
            label,
            system_prompt,
            model,
            json.dumps(params or {}, sort_keys=True),
            parent_version_id,
            int(is_published),
            created_at or now_iso(),
        ),
    )
    conn.commit()
    return vid


def get_version(conn: sqlite3.Connection, version_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM agent_versions WHERE id = ?", (version_id,)).fetchone()
    return _version_row(row) if row else None


def get_version_by_label(conn: sqlite3.Connection, label: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM agent_versions WHERE label = ?", (label,)).fetchone()
    return _version_row(row) if row else None


def resolve_version(conn: sqlite3.Connection, label_or_id: str) -> Optional[dict[str, Any]]:
    return get_version_by_label(conn, label_or_id) or get_version(conn, label_or_id)


def list_versions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM agent_versions ORDER BY created_at").fetchall()
    return [_version_row(r) for r in rows]


def get_published_version(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM agent_versions WHERE is_published = 1 ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return _version_row(row) if row else None


def set_published(conn: sqlite3.Connection, version_id: str, published: bool = True) -> None:
    if published:
        conn.execute("UPDATE agent_versions SET is_published = 0")
    conn.execute(
        "UPDATE agent_versions SET is_published = ? WHERE id = ?",
        (int(published), version_id),
    )
    conn.commit()


def _version_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json") or "{}")
    d["is_published"] = bool(d["is_published"])
    return d


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------

def insert_run(
    conn: sqlite3.Connection,
    *,
    agent_version_id: str,
    input: dict[str, Any],
    output: dict[str, Any],
    spans: list[dict[str, Any]],
    ground_truth_ref: Optional[str],
    latency_ms: float,
    total_cost_usd: float,
    created_at: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    rid = id or new_id()
    conn.execute(
        """INSERT INTO runs
           (id, agent_version_id, input_json, output_json, spans_json,
            ground_truth_ref, latency_ms, total_cost_usd, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rid,
            agent_version_id,
            json.dumps(input, sort_keys=True),
            json.dumps(output, sort_keys=True),
            json.dumps(spans),
            ground_truth_ref,
            latency_ms,
            total_cost_usd,
            created_at or now_iso(),
        ),
    )
    conn.commit()
    return rid


def get_run(conn: sqlite3.Connection, run_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _run_row(row) if row else None


def list_runs(
    conn: sqlite3.Connection, *, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    return [_run_row(r) for r in rows]


def count_runs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["input"] = json.loads(d.pop("input_json"))
    d["output"] = json.loads(d.pop("output_json"))
    d["spans"] = json.loads(d.pop("spans_json") or "[]")
    return d


# --------------------------------------------------------------------------
# eval_cases
# --------------------------------------------------------------------------

def insert_eval_case(
    conn: sqlite3.Connection,
    *,
    title: str,
    input: dict[str, Any],
    context_snapshot: dict[str, Any],
    rubric: str,
    reference_behavior: str,
    severity: str = "medium",
    status: str = "active",
    source_run_id: Optional[str] = None,
    first_failed_version_id: Optional[str] = None,
    fixed_in_version_id: Optional[str] = None,
    created_at: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    cid = id or new_id()
    conn.execute(
        """INSERT INTO eval_cases
           (id, source_run_id, title, input_json, context_snapshot_json, rubric,
            reference_behavior, severity, status, first_failed_version_id,
            fixed_in_version_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cid,
            source_run_id,
            title,
            json.dumps(input, sort_keys=True),
            json.dumps(context_snapshot, sort_keys=True),
            rubric,
            reference_behavior,
            severity,
            status,
            first_failed_version_id,
            fixed_in_version_id,
            created_at or now_iso(),
        ),
    )
    conn.commit()
    return cid


def get_eval_case(conn: sqlite3.Connection, case_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM eval_cases WHERE id = ?", (case_id,)).fetchone()
    return _case_row(row) if row else None


def list_eval_cases(
    conn: sqlite3.Connection, *, status: Optional[str] = None
) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM eval_cases WHERE status = ? ORDER BY created_at", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM eval_cases ORDER BY created_at").fetchall()
    return [_case_row(r) for r in rows]


def set_case_fixed_in(conn: sqlite3.Connection, case_id: str, version_id: str) -> None:
    conn.execute(
        "UPDATE eval_cases SET fixed_in_version_id = ? WHERE id = ? AND fixed_in_version_id IS NULL",
        (version_id, case_id),
    )
    conn.commit()


def _case_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["input"] = json.loads(d.pop("input_json"))
    d["context_snapshot"] = json.loads(d.pop("context_snapshot_json") or "{}")
    return d


# --------------------------------------------------------------------------
# eval_results
# --------------------------------------------------------------------------

def upsert_eval_result(
    conn: sqlite3.Connection,
    *,
    eval_case_id: str,
    agent_version_id: str,
    passed: bool,
    score: float,
    judge_rationale: str,
    actual_output: dict[str, Any],
    output_hash: str,
    from_cache: bool = False,
    created_at: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    rid = id or new_id()
    conn.execute(
        """INSERT INTO eval_results
           (id, eval_case_id, agent_version_id, passed, score, judge_rationale,
            actual_output_json, output_hash, from_cache, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (eval_case_id, agent_version_id, output_hash) DO UPDATE SET
             passed = excluded.passed,
             score = excluded.score,
             judge_rationale = excluded.judge_rationale,
             actual_output_json = excluded.actual_output_json""",
        (
            rid,
            eval_case_id,
            agent_version_id,
            int(passed),
            score,
            judge_rationale,
            json.dumps(actual_output, sort_keys=True),
            output_hash,
            int(from_cache),
            created_at or now_iso(),
        ),
    )
    conn.commit()
    return rid


def get_cached_result(
    conn: sqlite3.Connection, eval_case_id: str, agent_version_id: str, output_hash: Optional[str] = None
) -> Optional[dict[str, Any]]:
    if output_hash is not None:
        row = conn.execute(
            """SELECT * FROM eval_results
               WHERE eval_case_id = ? AND agent_version_id = ? AND output_hash = ?
               ORDER BY created_at DESC LIMIT 1""",
            (eval_case_id, agent_version_id, output_hash),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM eval_results
               WHERE eval_case_id = ? AND agent_version_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (eval_case_id, agent_version_id),
        ).fetchone()
    return _result_row(row) if row else None


def list_results_for_version(
    conn: sqlite3.Connection, agent_version_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT r.* FROM eval_results r
           INNER JOIN (
             SELECT eval_case_id, MAX(created_at) AS mc
             FROM eval_results WHERE agent_version_id = ? GROUP BY eval_case_id
           ) latest ON latest.eval_case_id = r.eval_case_id AND latest.mc = r.created_at
           WHERE r.agent_version_id = ?""",
        (agent_version_id, agent_version_id),
    ).fetchall()
    return [_result_row(r) for r in rows]


def list_results_for_case(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM eval_results WHERE eval_case_id = ? ORDER BY created_at", (case_id,)
    ).fetchall()
    return [_result_row(r) for r in rows]


def _result_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["actual_output"] = json.loads(d.pop("actual_output_json"))
    d["passed"] = bool(d["passed"])
    d["from_cache"] = bool(d["from_cache"])
    return d


# --------------------------------------------------------------------------
# gate_runs
# --------------------------------------------------------------------------

def insert_gate_run(
    conn: sqlite3.Connection,
    *,
    candidate_version_id: str,
    baseline_version_id: str,
    total_cases: int,
    passed_count: int,
    failed_count: int,
    regressed_case_ids: list[str],
    newly_fixed_case_ids: list[str],
    verdict: str,
    created_at: Optional[str] = None,
    id: Optional[str] = None,
) -> str:
    gid = id or new_id()
    conn.execute(
        """INSERT INTO gate_runs
           (id, candidate_version_id, baseline_version_id, total_cases, passed_count,
            failed_count, regressed_case_ids_json, newly_fixed_case_ids_json, verdict, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            gid,
            candidate_version_id,
            baseline_version_id,
            total_cases,
            passed_count,
            failed_count,
            json.dumps(regressed_case_ids),
            json.dumps(newly_fixed_case_ids),
            verdict,
            created_at or now_iso(),
        ),
    )
    conn.commit()
    return gid


def list_gate_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gate_runs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_gate_row(r) for r in rows]


def _gate_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["regressed_case_ids"] = json.loads(d.pop("regressed_case_ids_json") or "[]")
    d["newly_fixed_case_ids"] = json.loads(d.pop("newly_fixed_case_ids_json") or "[]")
    return d
