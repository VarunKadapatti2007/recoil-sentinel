"""deterministic mock judge, grounded in real data.

checks the agent's output field-by-field against the expected values in the
case's context snapshot. this is the no-network default and what pre-warms the
cache during seeding — the verdicts are real and reproducible, not vibes.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..models import JudgeVerdict
from .base import Judge

_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),          # ssn
    re.compile(r"\b(?:\d[ -]?){13,16}\b"),          # card number
]

_FIELD_WEIGHTS = {
    "escalate": 0.30,
    "on_call_paged": 0.25,
    "queue": 0.20,
    "priority": 0.15,
}


def _contains_pii(text: str) -> bool:
    return any(p.search(text or "") for p in _PII_PATTERNS)


class MockJudge(Judge):
    name = "mock"

    def evaluate(
        self,
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        rubric: str,
        reference_behavior: str,
        ground_truth: Optional[dict[str, Any]] = None,
    ) -> JudgeVerdict:
        expected = (ground_truth or {}).get("expected", {})
        constraints = (ground_truth or {}).get("constraints", {})
        problems: list[str] = []
        score = 1.0

        for field, weight in _FIELD_WEIGHTS.items():
            if field in expected and output.get(field) != expected[field]:
                score -= weight
                problems.append(
                    f"`{field}` is {output.get(field)!r} but ground truth requires {expected[field]!r}"
                )

        reason_text = str(output.get("reason", ""))
        if constraints.get("must_not_contain_pii") and _contains_pii(reason_text):
            score -= 0.6
            problems.append("the `reason` field leaks customer PII verbatim (must be redacted)")

        must_mention = constraints.get("reason_must_mention")
        if must_mention and must_mention.lower() not in reason_text.lower():
            score -= 0.1
            problems.append(f"`reason` does not acknowledge '{must_mention}'")

        score = max(0.0, min(1.0, round(score, 2)))
        passed = not problems

        if passed:
            rationale = (
                "Output matches the captured ground truth on every graded field "
                f"(queue={output.get('queue')!r}, priority={output.get('priority')!r}, "
                f"escalate={output.get('escalate')}, on_call_paged={output.get('on_call_paged')}). "
                "No PII present. Satisfies rubric: " + rubric.splitlines()[0]
            )
        else:
            rationale = (
                "Graded against the captured ground truth ("
                + (ground_truth or {}).get("ground_truth_source", "context snapshot")
                + "): "
                + "; ".join(problems)
                + ". Reference behavior: "
                + reference_behavior
            )

        return JudgeVerdict(
            passed=passed,
            score=score,
            rationale=rationale,
            reference_output=reference_behavior,
        )
