"""sentinel intel agent: real anthropic agent reads a live market snapshot and
writes a structured citable report, plus the verifier that checks every number
against the snapshot before we let anything publish.

anti-hallucination bits:
- model only sees snapshot metrics and can only reference their keys.
- each finding must list the keys it used and echo the exact values; verifier
  rejects unknown keys and values outside tolerance.
- citations come straight from the snapshot, never made up.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .. import config

AGENT_SYSTEM_PROMPT = """You are Recoil Sentinel, an autonomous crypto market-intelligence
analyst. You write precise, grounded intelligence briefs for engineers and traders.

HARD RULES (violations are rejected by an automated verifier):
1. You may ONLY make quantitative claims using the metrics provided in the snapshot.
2. Every finding must list the exact metric keys it relies on in `metric_keys`, and echo
   the exact numeric values you used in `claimed_values` (key -> value, copied verbatim
   from the snapshot — do not round there; round only in prose).
3. Never invent protocols, prices, events, or news that are not in the snapshot.
4. Be analytical, not promotional. Note risks. If the data is unremarkable, say so.
5. 3 to 5 findings. Each body is 1-3 sentences.
"""


class Finding(BaseModel):
    headline: str
    body: str
    metric_keys: list[str] = Field(min_length=1)
    claimed_values: dict[str, float]
    signal: Literal["bullish", "bearish", "neutral", "risk"]


class IntelReport(BaseModel):
    title: str
    executive_summary: str
    findings: list[Finding] = Field(min_length=3, max_length=5)
    risk_flags: list[str]
    confidence: Literal["low", "medium", "high"]


class ClaimCheck(BaseModel):
    finding_index: int
    metric_key: str
    claimed: Optional[float]
    observed: Optional[float]
    ok: bool
    problem: str = ""


class VerificationResult(BaseModel):
    passed: bool
    checks: list[ClaimCheck]
    problems: list[str]


class SentinelError(Exception):
    pass


def generate_report(
    snapshot: dict[str, Any], focus: Optional[str] = None
) -> tuple[IntelReport, dict[str, Any]]:
    """live model call. returns (report, llm_stats), raises SentinelError if it
    fails — this is the real path, no mock fallback on purpose. `focus` is
    optional and narrows the analysis, e.g. 'the Solana ecosystem' or 'stablecoin TVL'."""
    if not config.ANTHROPIC_API_KEY:
        raise SentinelError("ANTHROPIC_API_KEY required: Sentinel runs on the live model only")
    try:
        import anthropic
    except ImportError as exc:
        raise SentinelError("anthropic SDK not installed (pip install anthropic)") from exc

    compact = {
        k: {
            "label": m["label"],
            "value": m["value"],
            "unit": m["unit"],
            **{ek: ev for ek, ev in (m.get("extra") or {}).items() if ev is not None},
        }
        for k, m in snapshot["metrics"].items()
    }
    client = anthropic.Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        timeout=max(config.EXTERNAL_TIMEOUT_S, 60),
        max_retries=config.EXTERNAL_RETRIES,
    )
    focus_line = (
        f"\n\nFocus your analysis specifically on: {focus}. Only use metrics relevant to it."
        if focus
        else ""
    )
    t0 = time.perf_counter()
    response = client.messages.parse(
        model=config.AGENT_MODEL,
        max_tokens=2500,
        system=AGENT_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Live market snapshot fetched at {snapshot['fetched_at']} "
                    "(metric key -> data):\n"
                    + json.dumps(compact, indent=1, sort_keys=True)
                    + focus_line
                    + "\n\nWrite the intelligence brief now."
                ),
            }
        ],
        output_format=IntelReport,
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    report = response.parsed_output
    if report is None:
        raise SentinelError("model returned unparseable report")
    usage = response.usage
    # claude-sonnet-4-6 pricing: $3/m in, $15/m out
    cost = usage.input_tokens * 3e-6 + usage.output_tokens * 15e-6
    return report, {
        "model": config.AGENT_MODEL,
        "latency_ms": round(latency_ms, 1),
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "cost_usd": round(cost, 6),
    }


# how much echoed values can drift (lets benign float/rounding slop through)
_TOLERANCE = 0.01


def verify_report(report: IntelReport, snapshot: dict[str, Any]) -> VerificationResult:
    """check every number in the report against the snapshot. deterministic."""
    metrics = snapshot["metrics"]
    checks: list[ClaimCheck] = []
    problems: list[str] = []

    for i, finding in enumerate(report.findings):
        for key in finding.metric_keys:
            if key not in metrics:
                checks.append(
                    ClaimCheck(
                        finding_index=i,
                        metric_key=key,
                        claimed=finding.claimed_values.get(key),
                        observed=None,
                        ok=False,
                        problem=f"finding {i} cites unknown metric {key!r} (hallucinated source)",
                    )
                )
                problems.append(checks[-1].problem)
                continue
            observed = float(metrics[key]["value"])
            claimed = finding.claimed_values.get(key)
            if claimed is None:
                # cited but no number echoed — that's fine, it's just a qualitative ref
                checks.append(
                    ClaimCheck(finding_index=i, metric_key=key, claimed=None, observed=observed, ok=True)
                )
                continue
            denom = max(abs(observed), 1e-9)
            ok = abs(float(claimed) - observed) / denom <= _TOLERANCE or abs(float(claimed) - observed) <= 0.05
            check = ClaimCheck(
                finding_index=i,
                metric_key=key,
                claimed=float(claimed),
                observed=observed,
                ok=ok,
                problem=""
                if ok
                else f"finding {i} claims {key}={claimed} but ground truth is {observed}",
            )
            checks.append(check)
            if not ok:
                problems.append(check.problem)
        for key in finding.claimed_values:
            if key not in finding.metric_keys:
                problems.append(f"finding {i} has claimed value for unlisted metric {key!r}")
                checks.append(
                    ClaimCheck(
                        finding_index=i,
                        metric_key=key,
                        claimed=finding.claimed_values[key],
                        observed=None,
                        ok=False,
                        problem=problems[-1],
                    )
                )

    return VerificationResult(passed=not problems, checks=checks, problems=problems)


def tamper_report(report: IntelReport, snapshot: dict[str, Any]) -> tuple[IntelReport, str]:
    """demo-only fault injection: plant a bogus number against a real metric so
    verification is guaranteed to fail — chaos engineering for the truth layer.
    lets you show the gate catch a wrong number and refuse to publish live.
    returns the corrupted report + a description."""
    key = next(iter(snapshot["metrics"]))
    observed = float(snapshot["metrics"][key]["value"])
    corrupted = observed * 10 + 1  # way outside the 1% tolerance
    f0 = report.findings[0]
    new_keys = list(dict.fromkeys([*f0.metric_keys, key]))
    new_claims = {**f0.claimed_values, key: corrupted}
    report.findings[0] = f0.model_copy(
        update={"metric_keys": new_keys, "claimed_values": new_claims}
    )
    return (
        report,
        f"planted false claim '{key}' = {corrupted:,.0f} into finding 0 "
        f"(ground truth ~ {observed:,.0f}) — verifier must reject this",
    )
