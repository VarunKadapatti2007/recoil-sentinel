"""runs the agent under test.

two paths:
- mock (default, deterministic, offline): the version's behavior profile.
- live: calls the anthropic api with the version's system prompt and a
  structured-output schema. wrapped with timeout/retries and a fallback to the
  mock path so no exception ever reaches the demo path.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Optional

from .. import config
from ..models import Span, TriageOutput
from .versions import behavior_for_label

log = logging.getLogger("recoil.agent")


class TriageAgentError(Exception):
    pass


def _simulated_spans(
    rng: random.Random, model: str, *, base_latency: Optional[float] = None
) -> tuple[list[Span], float, float]:
    """realistic apm-style spans: one llm span + 1-2 tool spans."""
    t = 0.0
    spans: list[Span] = []
    lookup_ms = rng.uniform(40, 180)
    spans.append(
        Span(
            name="ground_truth.lookup",
            type="tool",
            start_ms=t,
            end_ms=t + lookup_ms,
            attributes={"source": "mock://incident-history"},
        )
    )
    t += lookup_ms + rng.uniform(3, 12)
    llm_ms = base_latency if base_latency is not None else rng.uniform(600, 2400)
    prompt_tokens = rng.randint(420, 980)
    completion_tokens = rng.randint(60, 190)
    # sonnet-class pricing: $3/m in, $15/m out — fractions of a cent per run.
    cost = prompt_tokens * 3e-6 + completion_tokens * 15e-6
    spans.append(
        Span(
            name="llm.triage_decision",
            type="llm",
            start_ms=t,
            end_ms=t + llm_ms,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost, 6),
            attributes={"temperature": 0},
        )
    )
    t += llm_ms + rng.uniform(2, 10)
    if rng.random() < 0.6:
        page_ms = rng.uniform(30, 140)
        spans.append(
            Span(
                name="pagerduty.evaluate",
                type="tool",
                start_ms=t,
                end_ms=t + page_ms,
                attributes={"provider": "pagerduty"},
            )
        )
        t += page_ms
    total_latency = t
    total_cost = sum(s.cost_usd or 0.0 for s in spans)
    return spans, total_latency, round(total_cost, 6)


def _run_mock(version: dict[str, Any], input: dict[str, Any], rng: random.Random) -> TriageOutput:
    behavior = behavior_for_label(version["label"])
    return behavior(input)


def _run_live(version: dict[str, Any], input: dict[str, Any]) -> TriageOutput:
    """live anthropic call with structured output. raises TriageAgentError on failure."""
    try:
        import anthropic  # lazy import, optional dep
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise TriageAgentError("anthropic SDK not installed") from exc

    client = anthropic.Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        timeout=config.EXTERNAL_TIMEOUT_S,
        max_retries=config.EXTERNAL_RETRIES,
    )
    try:
        response = client.messages.parse(
            model=version.get("model") or config.AGENT_MODEL,
            max_tokens=1024,
            system=version["system_prompt"],
            messages=[
                {
                    "role": "user",
                    "content": "Triage this incoming alert/message:\n"
                    + json.dumps(input, indent=2, sort_keys=True),
                }
            ],
            output_format=TriageOutput,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise TriageAgentError("model returned unparseable output")
        return parsed
    except TriageAgentError:
        raise
    except Exception as exc:
        raise TriageAgentError(f"live agent call failed: {exc}") from exc


def run_agent(
    version: dict[str, Any],
    input: dict[str, Any],
    *,
    live: bool = False,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    """run the agent and return a trace payload:
    {output, spans, latency_ms, total_cost_usd, ground_truth_ref}
    never raises on the demo path — live failures fall back to mock with a loud log.
    """
    rng = random.Random(seed)
    start = time.perf_counter()
    output: TriageOutput
    used_live = False
    if live and config.ANTHROPIC_API_KEY and not config.DEMO_MODE:
        try:
            output = _run_live(version, input)
            used_live = True
        except TriageAgentError as exc:
            log.warning("live agent failed (%s); falling back to deterministic mock", exc)
            output = _run_mock(version, input, rng)
    else:
        output = _run_mock(version, input, rng)

    elapsed_ms = (time.perf_counter() - start) * 1000
    base_latency = elapsed_ms if used_live and elapsed_ms > 100 else None
    spans, latency_ms, total_cost = _simulated_spans(
        rng, version.get("model") or config.AGENT_MODEL, base_latency=base_latency
    )
    return {
        "output": output.model_dump(),
        "spans": [s.model_dump() for s in spans],
        "latency_ms": round(latency_ms, 1),
        "total_cost_usd": total_cost,
        "ground_truth_ref": input.get("ground_truth_ref", "mock://incident-history"),
    }
