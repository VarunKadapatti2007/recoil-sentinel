"""Sponsor integrations for the Sentinel pipeline. Every integration:
- activates only when its credentials are configured,
- runs the REAL service (no mocks),
- degrades to a clear status string on failure — a sponsor outage must never
  block the publish loop.

ClickHouse  : every sentinel run is mirrored to ClickHouse Cloud (HTTPS
              interface, JSONEachRow) for real-time analytics.
Composio    : on a successful publish the agent ACTS on the web — it opens a
              real GitHub issue carrying the report summary + cited.md link.
Airbyte     : ground-truth control plane — client-credentials auth, workspace
              reachability, connection listing and (when present) sync trigger.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .. import config

log = logging.getLogger("recoil.sentinel")

# ---------------------------------------------------------------------------
# ClickHouse (Phase C)
# ---------------------------------------------------------------------------

_CH_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS sentinel_runs (
    run_id String,
    ts DateTime64(3, 'UTC'),
    verdict LowCardinality(String),
    claims_total UInt32,
    claims_ok UInt32,
    findings UInt32,
    model LowCardinality(String),
    prompt_tokens UInt32,
    completion_tokens UInt32,
    cost_usd Float64,
    latency_ms Float64,
    title String
) ENGINE = MergeTree ORDER BY ts
"""


def _ch_query(sql: str, *, body: Optional[str] = None) -> str:
    resp = httpx.post(
        config.CLICKHOUSE_HOST,
        params={"query": sql},
        content=body or b"",
        auth=(config.CLICKHOUSE_USER, config.CLICKHOUSE_PASSWORD),
        # ClickHouse Cloud idles between runs; waking can exceed the default
        # external timeout, so give this integration a longer leash.
        timeout=max(config.EXTERNAL_TIMEOUT_S, 60.0),
    )
    resp.raise_for_status()
    return resp.text


def clickhouse_record_run(
    *,
    run_id: str,
    verdict: str,
    claims_total: int,
    claims_ok: int,
    findings: int,
    llm_stats: dict[str, Any],
    title: str,
) -> str:
    """Mirror one sentinel run into ClickHouse. Returns a status string."""
    if not (config.CLICKHOUSE_HOST and config.CLICKHOUSE_PASSWORD):
        return "skipped (not configured)"
    try:
        _ch_query(_CH_TABLE_DDL)
        row = {
            "run_id": run_id,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "verdict": verdict,
            "claims_total": claims_total,
            "claims_ok": claims_ok,
            "findings": findings,
            "model": llm_stats.get("model", ""),
            "prompt_tokens": llm_stats.get("prompt_tokens", 0),
            "completion_tokens": llm_stats.get("completion_tokens", 0),
            "cost_usd": llm_stats.get("cost_usd", 0.0),
            "latency_ms": llm_stats.get("latency_ms", 0.0),
            "title": title,
        }
        _ch_query("INSERT INTO sentinel_runs FORMAT JSONEachRow", body=json.dumps(row))
        count = _ch_query("SELECT count() FROM sentinel_runs").strip()
        return f"recorded (table now holds {count} runs)"
    except Exception as exc:
        log.warning("clickhouse integration degraded: %s", exc)
        return f"degraded ({type(exc).__name__}: {exc})"


def clickhouse_stats() -> Optional[dict[str, Any]]:
    """Aggregate stats for the dashboard/status endpoint. None if unavailable."""
    if not (config.CLICKHOUSE_HOST and config.CLICKHOUSE_PASSWORD):
        return None
    try:
        raw = _ch_query(
            "SELECT count() AS runs, sum(cost_usd) AS total_cost, avg(latency_ms) AS avg_latency,"
            " countIf(verdict = 'PASS') AS passes FROM sentinel_runs FORMAT JSONEachRow"
        ).strip()
        return json.loads(raw) if raw else None
    except Exception as exc:
        log.warning("clickhouse stats unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Composio (Phase D)
# ---------------------------------------------------------------------------

def composio_publish_action(
    *,
    title: str,
    summary: str,
    run_id: str,
    claims_ok: int,
    claims_total: int,
) -> str:
    """The agent acts on the web: open a real GitHub issue announcing the report.
    Returns a status string (issue URL on success)."""
    if not config.COMPOSIO_API_KEY:
        return "skipped (not configured)"
    try:
        from composio import Composio  # lazy: optional dependency

        client = Composio(api_key=config.COMPOSIO_API_KEY)
        body = (
            f"{summary}\n\n"
            f"- **Run:** `{run_id}`\n"
            f"- **Claims verified:** {claims_ok}/{claims_total} against live ground truth\n"
            f"- **Full report:** https://github.com/{config.COMPOSIO_GITHUB_OWNER}/"
            f"{config.COMPOSIO_GITHUB_REPO}/blob/main/cited.md\n\n"
            "_Opened autonomously by Recoil Sentinel after the report passed its "
            "claim-verification gate._"
        )
        result = client.tools.execute(
            "GITHUB_CREATE_AN_ISSUE",
            {
                "owner": config.COMPOSIO_GITHUB_OWNER,
                "repo": config.COMPOSIO_GITHUB_REPO,
                "title": f"[Sentinel] {title}",
                "body": body,
            },
            user_id=config.COMPOSIO_USER_ID,
            connected_account_id=config.COMPOSIO_CONNECTED_ACCOUNT_ID or None,
            # one stable tool; schema drift is tolerated via graceful degradation
            dangerously_skip_version_check=True,
        )
        data = result.get("data", {}) if isinstance(result, dict) else {}
        url = data.get("html_url") or data.get("url") or ""
        if result.get("successful") or result.get("success"):
            return f"github issue created: {url}" if url else "github issue created"
        return f"degraded (composio returned: {result.get('error') or result})"
    except Exception as exc:
        log.warning("composio integration degraded: %s", exc)
        return f"degraded ({type(exc).__name__}: {exc})"


# ---------------------------------------------------------------------------
# Senso / cited.md — publish the verified report to the agentic content layer
# ---------------------------------------------------------------------------

def senso_publish_citeable(*, title: str, summary: str, markdown: str) -> str:
    """Publish a verified report to Senso (the platform behind cited.md) via the
    real API (apiv2.senso.ai, POST /org/kb/raw). Only fires after the report has
    PASSED claim verification — so Senso only ever receives machine-verified,
    grounded content. Returns a status string with the Senso content id."""
    if not config.SENSO_API_KEY:
        return "skipped (set SENSO_API_KEY to publish to cited.md)"
    headers = {"X-API-Key": config.SENSO_API_KEY, "Content-Type": "application/json"}
    try:
        # Preferred path: publish a LIVE article on the public cited.md page via the
        # content engine (needs a GEO question id + the Cited.md publisher id).
        if config.SENSO_GEO_QUESTION_ID and config.SENSO_PUBLISHER_ID:
            resp = httpx.post(
                f"{config.SENSO_API_BASE}/org/content-engine/publish",
                headers=headers,
                json={
                    "geo_question_id": config.SENSO_GEO_QUESTION_ID,
                    "raw_markdown": markdown,
                    "seo_title": title[:110],
                    "summary": summary[:480],
                    "publisher_ids": [config.SENSO_PUBLISHER_ID],
                },
                timeout=max(config.EXTERNAL_TIMEOUT_S, 45.0),
            )
            if resp.status_code in (200, 201):
                data = resp.json() if resp.content else {}
                dests = data.get("publish_destinations") or []
                url = dests[0].get("display_url") if dests else ""
                if data.get("publish_status") == "success" and url:
                    return f"published LIVE to cited.md: {url}"
                return f"published to cited.md ({data.get('publish_status', 'queued')})"
            log.warning("senso engine publish %s: %s — falling back to KB", resp.status_code, resp.text[:160])

        # Fallback: ingest into the org knowledge base (still real Senso usage).
        resp = httpx.post(
            f"{config.SENSO_API_BASE}/org/kb/raw",
            headers=headers,
            json={"title": title[:120], "summary": summary[:480], "text": markdown},
            timeout=max(config.EXTERNAL_TIMEOUT_S, 30.0),
        )
        if resp.status_code in (200, 201, 202):
            data = resp.json() if resp.content else {}
            cid = data.get("id") or data.get("content_id") or ""
            return f"ingested into Senso KB (content {cid}; set SENSO_GEO_QUESTION_ID for live cited.md)"
        return f"degraded (Senso {resp.status_code}: {resp.text[:160]})"
    except Exception as exc:
        log.warning("senso/cited.md publish degraded: %s", exc)
        return f"degraded ({type(exc).__name__}: {exc})"


# ---------------------------------------------------------------------------
# Airbyte (Phase B)
# ---------------------------------------------------------------------------

_AIRBYTE_API = "https://api.airbyte.com/v1"


def _airbyte_token(client: httpx.Client) -> str:
    resp = client.post(
        f"{_AIRBYTE_API}/applications/token",
        json={
            "client_id": config.AIRBYTE_CLIENT_ID,
            "client_secret": config.AIRBYTE_CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def airbyte_ground_truth_check(*, trigger_sync: bool = False) -> str:
    """Verify the Airbyte ground-truth control plane: authenticate with client
    credentials, confirm workspace reachability, list connections, optionally
    trigger a sync of the first one. Returns a status string."""
    if not (config.AIRBYTE_CLIENT_ID and config.AIRBYTE_CLIENT_SECRET):
        return "skipped (not configured)"
    try:
        with httpx.Client(timeout=config.EXTERNAL_TIMEOUT_S) as client:
            token = _airbyte_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            params = (
                {"workspaceIds": config.AIRBYTE_WORKSPACE_ID}
                if config.AIRBYTE_WORKSPACE_ID
                else {}
            )
            resp = client.get(f"{_AIRBYTE_API}/connections", headers=headers, params=params)
            resp.raise_for_status()
            connections = resp.json().get("data", [])
            if not connections:
                return "authenticated (workspace reachable, no connections configured yet)"
            status = f"authenticated ({len(connections)} connection(s))"
            if trigger_sync:
                job = client.post(
                    f"{_AIRBYTE_API}/jobs",
                    headers=headers,
                    json={"connectionId": connections[0]["connectionId"], "jobType": "sync"},
                )
                job.raise_for_status()
                status += f"; sync job {job.json().get('jobId')} triggered"
            return status
    except Exception as exc:
        log.warning("airbyte integration degraded: %s", exc)
        return f"degraded ({type(exc).__name__}: {exc})"
