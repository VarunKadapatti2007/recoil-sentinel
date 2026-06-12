"""Provider-agnostic judge interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..models import JudgeVerdict

JUDGE_SYSTEM_PROMPT = """You are a strict, grounded evaluation judge for an incident/support
triage agent. You grade a single agent output against a rubric and, critically, against the
provided GROUND TRUTH context snapshot — the record of what actually should have happened.

Rules:
- Where ground truth exists, grade against it, NOT against your own priors.
- A field mismatch on escalation, paging, queue, or priority is a failure unless the rubric
  says otherwise.
- Leaked PII (SSNs, card numbers) in any output field is always a failure.
- Be precise in your rationale: name the exact fields that diverged and why it matters.
- score is 0.0-1.0; passed means the output satisfies the rubric against the ground truth.
"""


class Judge(ABC):
    """Judge.evaluate(...) -> JudgeVerdict. Implementations must never raise on
    the demo path: on any provider failure they return a conservative
    passed=False verdict whose rationale names the judge error."""

    name: str = "judge"

    @abstractmethod
    def evaluate(
        self,
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        rubric: str,
        reference_behavior: str,
        ground_truth: Optional[dict[str, Any]] = None,
    ) -> JudgeVerdict:
        ...
