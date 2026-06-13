"""seed a believable prod history + the frozen 12-case regression suite.

everything here is deterministic (seeded rng, mock judge, behavior profiles),
so `recoil reset --demo` rebuilds a byte-stable demo state in well under 2s,
and every cached verdict is a real, reproducible call grounded in the captured
context snapshots.

what we seed:
- 5 agent versions: v1 -> v2 -> v_good (published) -> v_regressed / v_fixed
- ~250 prod runs across v1/v2/v_good over a ~18-day window, with varied
  latencies, token counts, and per-run cost
- exactly 12 frozen eval cases, each promoted from a real seeded failure run
  (we actually run the promotion pipeline, don't fake it)
- cached judge verdicts for v_good / v_regressed / v_fixed (and the old
  versions) against all 12 cases — the demo's block/pass path is fully cached
- one old gate run (v_good vs v2, pass) so the dashboard opens green
- the local ground-truth store + optionally pre-rendered voice verdicts
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .adapters.ground_truth import LocalJSONGroundTruth
from .agent import run_agent
from .agent.versions import VERSION_SPECS, behavior_for_label
from .evals.promotion import promote_failure_to_case
from .evals.runner import judge_case
from .judge.mock_judge import MockJudge
from .tracing import capture_run
from .voice import prerender_verdicts

SEED = 1337
RUN_COUNT = 250
WINDOW_DAYS = 18

# ---------------------------------------------------------------------------
# the 12 frozen case defs (brief §7 archetypes). `first_failed` is the old
# version whose real failure run gets promoted into the case.
# ---------------------------------------------------------------------------
CASE_DEFS: list[dict[str, Any]] = [
    {
        "key": "hero_after_hours_outage",
        "title": "After-hours DB outage must escalate P1",
        "severity": "critical",
        "first_failed": "v2",
        "input": {
            "kind": "outage",
            "scope": "full",
            "title": "Primary Postgres cluster unreachable",
            "message": "ALERT db-primary-01: connection refused on 5432; replica lag growing; checkout failing for all tenants.",
            "channel": "pagerduty-webhook",
            "local_hour": 2,
            "region": "us-east-1",
            "customer_impact": True,
        },
        "constraints": {"reason_must_mention": "on-call"},
    },
    {
        "key": "pii_redaction",
        "title": "Agent must redact a customer SSN in its reason field",
        "severity": "critical",
        "first_failed": "v1",
        "input": {
            "kind": "pii_leak",
            "title": "Customer pasted SSN into ticket",
            "message": "Hi, I can't log in. My SSN is 123-45-6789 if you need to verify me.",
            "pii_sample": "SSN 123-45-6789",
            "channel": "zendesk",
            "local_hour": 14,
        },
        "constraints": {"must_not_contain_pii": True},
    },
    {
        "key": "billing_routing",
        "title": "Billing dispute routed to billing, not engineering",
        "severity": "medium",
        "first_failed": "v1",
        "input": {
            "kind": "billing",
            "title": "Charged twice for March invoice",
            "message": "We were billed $4,200 twice this cycle. Please reverse the duplicate charge.",
            "channel": "email",
            "local_hour": 11,
        },
    },
    {
        "key": "non_english_routing",
        "title": "Non-English ticket language-detected and routed",
        "severity": "medium",
        "first_failed": "v1",
        "input": {
            "kind": "non_english",
            "language": "ja",
            "title": "ダッシュボードにアクセスできません",
            "message": "ダッシュボードにログインできず、エラー503が表示されます。至急対応をお願いします。",
            "channel": "zendesk",
            "local_hour": 10,
        },
    },
    {
        "key": "password_reset_no_page",
        "title": "Password reset must NOT page on-call",
        "severity": "low",
        "first_failed": "v1",
        "input": {
            "kind": "password_reset",
            "title": "How do I reset my password?",
            "message": "Forgot my password, the reset email never arrived. How do I reset it?",
            "channel": "chat",
            "local_hour": 15,
        },
    },
    {
        "key": "vague_slow_p3",
        "title": "Ambiguous 'site feels slow' triaged P3, not dismissed",
        "severity": "medium",
        "first_failed": "v1",
        "input": {
            "kind": "vague_slow",
            "title": "Site feels slow today",
            "message": "Pages take forever to load since this morning. Nothing in your status page though?",
            "channel": "email",
            "local_hour": 9,
        },
    },
    {
        "key": "duplicate_suppressed",
        "title": "Duplicate alert suppressed, not re-triaged",
        "severity": "low",
        "first_failed": "v2",
        "input": {
            "kind": "duplicate",
            "title": "ALERT api-gw 5xx spike (repeat)",
            "message": "Duplicate of INC-2291 (already acknowledged): api-gateway 5xx ratio above 2%.",
            "channel": "datadog-webhook",
            "local_hour": 13,
            "duplicate_of": "INC-2291",
        },
    },
    {
        "key": "security_queue",
        "title": "Suspected breach escalated to the security queue",
        "severity": "critical",
        "first_failed": "v2",
        "input": {
            "kind": "security",
            "title": "Possible credential stuffing on login endpoint",
            "message": "Seeing 40k failed logins from rotating IPs in 10 minutes; some accounts now report unfamiliar sessions.",
            "channel": "siem-webhook",
            "local_hour": 16,
        },
    },
    {
        "key": "churn_risk_review",
        "title": "Angry churn-risk customer flagged for human review",
        "severity": "high",
        "first_failed": "v2",
        "input": {
            "kind": "churn_risk",
            "title": "Cancel our contract",
            "message": "Third outage this quarter. If this isn't resolved this week we're moving to a competitor. Unacceptable.",
            "channel": "email",
            "local_hour": 12,
            "account_tier": "enterprise",
        },
    },
    {
        "key": "feature_request_product",
        "title": "Feature request routed to product, not support",
        "severity": "low",
        "first_failed": "v1",
        "input": {
            "kind": "feature_request",
            "title": "Please add SAML SSO",
            "message": "Would love SAML SSO support for our okta org. Any timeline?",
            "channel": "zendesk",
            "local_hour": 10,
        },
    },
    {
        "key": "partial_regional_outage",
        "title": "Partial eu-west-1 outage escalated appropriately",
        "severity": "high",
        "first_failed": "v2",
        "input": {
            "kind": "outage",
            "scope": "partial",
            "title": "Elevated error rate in eu-west-1",
            "message": "ALERT: 38% of requests in eu-west-1 returning 502; other regions healthy; EU customers impacted.",
            "channel": "pagerduty-webhook",
            "local_hour": 22,
            "region": "eu-west-1",
            "customer_impact": True,
        },
    },
    {
        "key": "false_positive_deprioritized",
        "title": "Known false-positive disk alert de-prioritized",
        "severity": "medium",
        "first_failed": "v2",
        "input": {
            "kind": "false_positive",
            "title": "ALERT disk usage 91% on batch-worker-07",
            "message": "Known noisy monitor: batch-worker scratch disk fills during nightly ETL and self-cleans (see RUNBOOK-114).",
            "channel": "datadog-webhook",
            "local_hour": 3,
            "runbook": "RUNBOOK-114",
        },
    },
]

# boring traffic templates for the 250-run history
_TRAFFIC_KINDS = (
    ("support", 0.30),
    ("password_reset", 0.16),
    ("billing", 0.14),
    ("outage", 0.06),
    ("vague_slow", 0.08),
    ("feature_request", 0.10),
    ("duplicate", 0.06),
    ("non_english", 0.05),
    ("churn_risk", 0.03),
    ("false_positive", 0.02),
)

_TRAFFIC_TITLES = {
    "support": [
        "Can't export CSV from reports",
        "Webhook retries not firing",
        "API key rotation question",
        "Sandbox env behaving differently",
        "Need help configuring alerts",
    ],
    "password_reset": ["Password reset email missing", "Locked out of account", "2FA reset request"],
    "billing": ["Invoice discrepancy", "Upgrade plan mid-cycle?", "Tax ID missing on invoice"],
    "outage": ["Elevated 5xx on api-gateway", "Ingestion lag above SLO", "Dashboard widgets timing out"],
    "vague_slow": ["Everything feels sluggish", "Slow page loads reported by team"],
    "feature_request": ["Dark mode please", "Terraform provider request", "Audit log export API"],
    "duplicate": ["ALERT repeat: queue depth high", "Duplicate page: cert expiry warning"],
    "non_english": ["No puedo acceder al panel", "Je ne peux pas me connecter"],
    "churn_risk": ["Considering alternatives", "Escalation: repeated issues"],
    "false_positive": ["ALERT scratch disk 90% (known)", "Noisy monitor: ETL CPU spike"],
}


def _expected_for(input: dict[str, Any]) -> dict[str, Any]:
    """ground truth = what the policy-correct triage outputs for this input."""
    out = behavior_for_label("v_good")(input)
    return {
        "queue": out.queue,
        "priority": out.priority,
        "escalate": out.escalate,
        "on_call_paged": out.on_call_paged,
    }


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def seed_all(conn: sqlite3.Connection, *, verbose: bool = False) -> dict[str, Any]:
    rng = random.Random(SEED)
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=WINDOW_DAYS)

    def say(msg: str) -> None:
        if verbose:
            print(f"  {msg}")

    # --- 1. agent versions -------------------------------------------------
    version_ids: dict[str, str] = {}
    parent: str | None = None
    created = t0
    for spec in VERSION_SPECS:
        vid = db.insert_agent_version(
            conn,
            label=spec["label"],
            system_prompt=spec["system_prompt"],
            model="claude-sonnet-4-6",
            params={"temperature": 0, "max_tokens": 1024},
            parent_version_id=parent if spec["label"] != "v_fixed" else version_ids["v_good"],
            is_published=spec["is_published"],
            created_at=_iso(created),
        )
        version_ids[spec["label"]] = vid
        parent = vid if spec["label"] in ("v1", "v2", "v_good") else parent
        created += timedelta(days=4 if spec["label"] in ("v1", "v2") else 2)
    say(f"versions: {', '.join(version_ids)}")

    # --- 2. production run history ------------------------------------------
    # overlapping rollout: v1 days 0-5, v2 days 4-11, v_good days 10-18
    schedule = [
        ("v1", 0.0, 5.5, 50),
        ("v2", 4.0, 11.5, 85),
        ("v_good", 10.0, float(WINDOW_DAYS), RUN_COUNT - 50 - 85 - len(CASE_DEFS)),
    ]
    kinds, weights = zip(*_TRAFFIC_KINDS)
    run_count = 0
    for label, d_start, d_end, n in schedule:
        version = db.get_version(conn, version_ids[label])
        assert version is not None
        for _ in range(n):
            kind = rng.choices(kinds, weights=weights, k=1)[0]
            title = rng.choice(_TRAFFIC_TITLES[kind])
            inp: dict[str, Any] = {
                "kind": kind,
                "title": title,
                "message": title + ".",
                "channel": rng.choice(["zendesk", "email", "chat", "pagerduty-webhook"]),
                "local_hour": rng.randint(0, 23) if kind == "outage" else rng.randint(8, 19),
            }
            if kind == "outage":
                inp["scope"] = rng.choice(["full", "partial"])
                inp["region"] = rng.choice(["us-east-1", "eu-west-1", "ap-southeast-2"])
                inp["customer_impact"] = True
            if kind == "non_english":
                inp["language"] = rng.choice(["es", "fr", "de"])
            trace = run_agent(version, inp, seed=rng.randint(0, 2**31))
            ts = t0 + timedelta(days=rng.uniform(d_start, d_end))
            capture_run(
                conn,
                agent_version_id=version["id"],
                input=inp,
                trace=trace,
                created_at=_iso(ts),
            )
            run_count += 1
    say(f"production runs: {run_count}")

    # --- 3. turn the 12 failure runs into frozen eval cases ------------------
    judge = MockJudge()
    gt_store: dict[str, Any] = {}
    case_ids: dict[str, str] = {}
    for i, cdef in enumerate(CASE_DEFS):
        fail_label = cdef["first_failed"]
        version = db.get_version(conn, version_ids[fail_label])
        assert version is not None
        expected = _expected_for(cdef["input"])
        constraints = dict(cdef.get("constraints", {}))
        constraints.setdefault("must_not_contain_pii", True)
        gt_ref = f"gt://{cdef['key']}"
        gt_store[gt_ref] = {"expected": expected, "constraints": constraints}

        run_input = {
            **cdef["input"],
            "ground_truth_ref": gt_ref,
            "_expected": expected,
            "_constraints": constraints,
        }
        trace = run_agent(version, run_input, seed=SEED + i)
        # these failures happened back when that version was live
        fail_day = rng.uniform(1.0, 5.0) if fail_label == "v1" else rng.uniform(5.0, 10.0)
        run_id = capture_run(
            conn,
            agent_version_id=version["id"],
            input=run_input,
            trace=trace,
            created_at=_iso(t0 + timedelta(days=fail_day)),
        )
        run_count += 1

        ground_truth = {"expected": expected, "constraints": constraints, "ground_truth_source": gt_ref}
        verdict = judge.evaluate(
            input=cdef["input"],
            output=trace["output"],
            rubric="",
            reference_behavior=_reference_behavior(expected),
            ground_truth=ground_truth,
        )
        assert not verdict.passed, f"seed integrity: {cdef['key']} must fail under {fail_label}"
        case_id = promote_failure_to_case(
            conn,
            run_id=run_id,
            verdict=verdict,
            title=cdef["title"],
            severity=cdef["severity"],
        )
        assert case_id is not None
        case_ids[cdef["key"]] = case_id
        # the case keeps its own judged fail for the version it came from
        from .judge import output_hash

        db.upsert_eval_result(
            conn,
            eval_case_id=case_id,
            agent_version_id=version["id"],
            passed=False,
            score=verdict.score,
            judge_rationale=verdict.rationale,
            actual_output=trace["output"],
            output_hash=output_hash(trace["output"]),
        )
    say(f"frozen eval cases: {len(case_ids)}")

    LocalJSONGroundTruth().write_store(gt_store)

    # --- 4. pre-warm cached verdicts for the demo versions -------------------
    # go in chronological order so fixed_in_version_id lands on the real fixer
    for label in ("v2", "v_good", "v_regressed", "v_fixed"):
        version = db.get_version(conn, version_ids[label])
        assert version is not None
        for case in db.list_eval_cases(conn, status="active"):
            # don't re-judge the recorded first failure (keeps history honest)
            if db.get_cached_result(conn, case["id"], version["id"]) is not None:
                continue
            # v2 only has history for cases that were already frozen by then
            if label == "v2" and case["first_failed_version_id"] != version_ids["v1"]:
                continue
            judge_case(conn, case, version, use_cache=False)
    say("cached verdicts pre-warmed for v2/v_good/v_regressed/v_fixed")

    # --- 5. one old pass gate run so the dashboard opens green ---------------
    db.insert_gate_run(
        conn,
        candidate_version_id=version_ids["v_good"],
        baseline_version_id=version_ids["v2"],
        total_cases=len(case_ids),
        passed_count=len(case_ids),
        failed_count=0,
        regressed_case_ids=[],
        newly_fixed_case_ids=[case_ids[c["key"]] for c in CASE_DEFS if c["first_failed"] == "v2"],
        verdict="PASS",
        created_at=_iso(now - timedelta(days=6)),
    )

    # --- 6. optional voice pre-render (no-op without elevenlabs key) ---------
    audio = prerender_verdicts()

    return {
        "versions": version_ids,
        "runs": run_count,
        "cases": case_ids,
        "audio": audio,
    }


def _reference_behavior(expected: dict[str, Any]) -> str:
    return (
        f"Correct behavior: route to queue {expected['queue']!r} at priority "
        f"{expected['priority']}, escalate={expected['escalate']}, "
        f"on_call_paged={expected['on_call_paged']}; reason must be PII-free and "
        "acknowledge the captured incident context."
    )
