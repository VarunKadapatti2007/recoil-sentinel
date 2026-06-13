"""the three demo agent versions (plus older parents) and their deterministic
behavior profiles.

the behavior profiles are the offline/mock path: given a triage input they
produce exactly what the matching system prompt would get from the model. that's
what makes seeding and the demo path fully deterministic and offline. if an
ANTHROPIC_API_KEY is set and demo mode is off, the agent calls the live model
instead (see triage.py).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..models import TriageOutput

Behavior = Callable[[dict[str, Any]], TriageOutput]

_BASE_PROMPT = """You are an incident & support triage agent for Northbeam Cloud.
You receive an incoming alert or support message and must return a JSON object:
{"queue": str, "priority": "P1".."P4", "escalate": bool, "on_call_paged": bool, "reason": str}

Routing policy:
- Customer-impacting outages (full or partial, any region) are P1, escalate, page on-call — at any hour.
- Suspected security breaches go to the "security" queue, P1, escalate, page on-call.
- Billing disputes go to "billing". Feature requests go to "product". Password resets and
  how-to questions go to "support" at P4 and must NOT page on-call.
- Non-English tickets are language-detected and routed to the regional support queue.
- Angry customers with churn signals are flagged for human review ("retention" queue).
- Duplicate/spam alerts are suppressed (queue "suppressed", P4, no escalation).
- Known false-positive monitors are de-prioritized, not escalated.
- Ambiguous performance complaints ("site feels slow") are triaged P3 to "engineering"
  for investigation — never dismissed.
- NEVER include customer PII (SSNs, card numbers) in your reason field; redact it.
"""

_CONCISE_EDIT = """
Style update: be concise and reduce escalation noise. Only escalate clear
emergencies during business hours (09:00-18:00 local). Prefer lower priorities
when impact is uncertain. Keep `reason` under 20 words."""

_FIXED_EDIT = """
Style update: be concise — keep `reason` under 20 words. Reduce noise on
non-emergencies, BUT customer-impacting outages and security incidents are
ALWAYS emergencies regardless of business hours: P1, escalate, page on-call."""


def _redact(text: str) -> str:
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED-SSN]", text)
    text = re.sub(r"\b(?:\d[ -]?){13,16}\b", "[REDACTED-CARD]", text)
    return text


def _is_after_hours(inp: dict[str, Any]) -> bool:
    hour = int(inp.get("local_hour", 12))
    return hour < 9 or hour >= 18


def _correct_triage(inp: dict[str, Any]) -> TriageOutput:
    """the by-the-book triage decision — what v_good and v_fixed produce."""
    kind = inp.get("kind", "support")
    if kind == "outage":
        scope = inp.get("scope", "full")
        region = inp.get("region")
        detail = f" affecting {region}" if scope == "partial" and region else ""
        return TriageOutput(
            queue="incident",
            priority="P1",
            escalate=True,
            on_call_paged=True,
            reason=_redact(f"Customer-impacting {scope} outage{detail}; paging on-call per policy."),
        )
    if kind == "security":
        return TriageOutput(
            queue="security",
            priority="P1",
            escalate=True,
            on_call_paged=True,
            reason="Suspected breach; routed to security with on-call page.",
        )
    if kind == "pii_leak":
        return TriageOutput(
            queue="support",
            priority="P2",
            escalate=True,
            on_call_paged=False,
            reason=_redact(
                "Customer shared sensitive data "
                + inp.get("pii_sample", "")
                + "; data redacted and account flagged."
            ),
        )
    if kind == "billing":
        return TriageOutput(
            queue="billing",
            priority="P3",
            escalate=False,
            on_call_paged=False,
            reason="Billing dispute; routed to billing, not engineering.",
        )
    if kind == "non_english":
        lang = inp.get("language", "es")
        return TriageOutput(
            queue=f"support-{lang}",
            priority="P3",
            escalate=False,
            on_call_paged=False,
            reason=f"Detected language '{lang}'; routed to regional queue.",
        )
    if kind == "password_reset":
        return TriageOutput(
            queue="support",
            priority="P4",
            escalate=False,
            on_call_paged=False,
            reason="Routine password reset; self-serve docs linked, no page.",
        )
    if kind == "vague_slow":
        return TriageOutput(
            queue="engineering",
            priority="P3",
            escalate=False,
            on_call_paged=False,
            reason="Ambiguous latency report; opened P3 investigation, not dismissed.",
        )
    if kind == "duplicate":
        return TriageOutput(
            queue="suppressed",
            priority="P4",
            escalate=False,
            on_call_paged=False,
            reason="Duplicate of existing alert; suppressed.",
        )
    if kind == "churn_risk":
        return TriageOutput(
            queue="retention",
            priority="P2",
            escalate=True,
            on_call_paged=False,
            reason="Churn-risk language detected; flagged for human review.",
        )
    if kind == "feature_request":
        return TriageOutput(
            queue="product",
            priority="P4",
            escalate=False,
            on_call_paged=False,
            reason="Feature request; routed to product, not support.",
        )
    if kind == "false_positive":
        return TriageOutput(
            queue="monitoring",
            priority="P4",
            escalate=False,
            on_call_paged=False,
            reason="Known false-positive monitor; de-prioritized.",
        )
    return TriageOutput(
        queue="support",
        priority="P3",
        escalate=False,
        on_call_paged=False,
        reason="General support request.",
    )


def _v_good(inp: dict[str, Any]) -> TriageOutput:
    return _correct_triage(inp)


def _v_regressed(inp: dict[str, Any]) -> TriageOutput:
    """the plausible 'improvement' edit: concise + only escalate during business
    hours. quietly breaks the after-hours-outage class."""
    out = _correct_triage(inp)
    if inp.get("kind") in ("outage",) and _is_after_hours(inp):
        return TriageOutput(
            queue="engineering",
            priority="P3",
            escalate=False,
            on_call_paged=False,
            reason="Outage alert received; deferring to business hours.",
        )
    # trim reasons to stay concise
    words = out.reason.split()
    if len(words) > 20:
        out = out.model_copy(update={"reason": " ".join(words[:20])})
    return out


def _v_fixed(inp: dict[str, Any]) -> TriageOutput:
    """keeps the concise reasons but still escalates after hours."""
    out = _correct_triage(inp)
    words = out.reason.split()
    if len(words) > 20:
        out = out.model_copy(update={"reason": " ".join(words[:20])})
    return out


def _v1(inp: dict[str, Any]) -> TriageOutput:
    """early version with a few policy gaps (these failures seeded the suite)."""
    out = _correct_triage(inp)
    kind = inp.get("kind")
    if kind == "pii_leak":
        # leaks the pii verbatim into the reason
        return out.model_copy(
            update={
                "reason": "Customer shared sensitive data "
                + inp.get("pii_sample", "")
                + "; please verify identity."
            }
        )
    if kind == "billing":
        return out.model_copy(update={"queue": "engineering"})
    if kind == "non_english":
        return out.model_copy(update={"queue": "support", "reason": "Could not parse ticket text."})
    if kind == "password_reset":
        return out.model_copy(update={"priority": "P2", "escalate": True, "on_call_paged": True})
    if kind == "vague_slow":
        return out.model_copy(
            update={"queue": "support", "priority": "P4", "reason": "Vague report; closing as works-for-me."}
        )
    if kind == "feature_request":
        return out.model_copy(update={"queue": "support"})
    return out


def _v2(inp: dict[str, Any]) -> TriageOutput:
    """second version: fixed v1's routing gaps, added new ones."""
    out = _correct_triage(inp)
    kind = inp.get("kind")
    if kind == "outage" and _is_after_hours(inp):
        # the original after-hours bug — the hero case was frozen from this
        return out.model_copy(update={"priority": "P2", "escalate": False, "on_call_paged": False})
    if kind == "security":
        return out.model_copy(update={"queue": "incident"})
    if kind == "duplicate":
        return out.model_copy(update={"queue": "incident", "priority": "P3"})
    if kind == "churn_risk":
        return out.model_copy(update={"queue": "support", "escalate": False})
    if kind == "false_positive":
        return out.model_copy(update={"priority": "P2", "escalate": True})
    if kind == "outage" and inp.get("scope") == "partial":
        return out.model_copy(update={"priority": "P2", "on_call_paged": False})
    return out


VERSION_SPECS: list[dict[str, Any]] = [
    {
        "label": "v1",
        "system_prompt": _BASE_PROMPT,
        "behavior": _v1,
        "is_published": False,
    },
    {
        "label": "v2",
        "system_prompt": _BASE_PROMPT + "\n(Refined routing rules after v1 incident review.)",
        "behavior": _v2,
        "is_published": False,
    },
    {
        "label": "v_good",
        "system_prompt": _BASE_PROMPT + "\n(Hardened after the after-hours escalation incident of v2.)",
        "behavior": _v_good,
        "is_published": True,
    },
    {
        "label": "v_regressed",
        "system_prompt": _BASE_PROMPT + _CONCISE_EDIT,
        "behavior": _v_regressed,
        "is_published": False,
    },
    {
        "label": "v_fixed",
        "system_prompt": _BASE_PROMPT + _FIXED_EDIT,
        "behavior": _v_fixed,
        "is_published": False,
    },
]

_BEHAVIORS: dict[str, Behavior] = {spec["label"]: spec["behavior"] for spec in VERSION_SPECS}


def behavior_for_label(label: str) -> Behavior:
    return _BEHAVIORS.get(label, _correct_triage)
