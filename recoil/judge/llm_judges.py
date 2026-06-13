"""llm-backed judges: anthropic direct, aws bedrock, openai.

every provider:
- asks for structured json validated against JudgeVerdict (with retries),
- has timeouts and bounded sdk retries,
- never raises: on failure returns a safe passed=False verdict that names the
  error and logs loudly.

model notes:
- anthropic default is `claude-opus-4-8`. opus 4.7+ / fable reject the
  `temperature` param, so we only send temperature=0 to models that take it.
- bedrock model ids have the `anthropic.` prefix, e.g. `anthropic.claude-opus-4-8`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .. import config
from ..models import JudgeVerdict
from .base import JUDGE_SYSTEM_PROMPT, Judge

log = logging.getLogger("recoil.judge")

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "score": {"type": "number"},
        "rationale": {"type": "string"},
        "reference_output": {"type": "string"},
    },
    "required": ["passed", "score", "rationale", "reference_output"],
    "additionalProperties": False,
}


def _judge_user_prompt(
    input: dict[str, Any],
    output: dict[str, Any],
    rubric: str,
    reference_behavior: str,
    ground_truth: Optional[dict[str, Any]],
) -> str:
    return (
        "Evaluate this agent run.\n\n"
        f"## Input\n{json.dumps(input, indent=2, sort_keys=True)}\n\n"
        f"## Agent output\n{json.dumps(output, indent=2, sort_keys=True)}\n\n"
        f"## Rubric\n{rubric}\n\n"
        f"## Reference behavior (what correct looks like)\n{reference_behavior}\n\n"
        f"## Ground truth context snapshot\n"
        f"{json.dumps(ground_truth or {}, indent=2, sort_keys=True)}\n\n"
        "Grade strictly against the ground truth. Respond with JSON only."
    )


def _error_verdict(provider: str, exc: Exception) -> JudgeVerdict:
    log.error("JUDGE PROVIDER FAILURE (%s): %s — returning conservative FAIL", provider, exc)
    return JudgeVerdict(
        passed=False,
        score=0.0,
        rationale=(
            f"[judge error] The {provider} judge could not produce a verdict ({exc}). "
            "Failing conservatively; re-run with a working judge before trusting this result."
        ),
        reference_output="",
    )


def _coerce_verdict(raw: str) -> JudgeVerdict:
    data = json.loads(raw)
    data["score"] = max(0.0, min(1.0, float(data.get("score", 0.0))))
    return JudgeVerdict.model_validate(data)


def _model_accepts_temperature(model: str) -> bool:
    """opus 4.7+, opus 4.8 and fable 5 dropped temperature (400 if you send it)."""
    m = model.lower()
    blocked = ("claude-opus-4-7", "claude-opus-4-8", "claude-fable", "claude-mythos")
    return not any(b in m for b in blocked)


class AnthropicJudge(Judge):
    name = "anthropic"

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or config.JUDGE_MODEL

    def _client(self):  # pragma: no cover - thin wrapper
        import anthropic

        return anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            timeout=config.EXTERNAL_TIMEOUT_S,
            max_retries=config.EXTERNAL_RETRIES,
        )

    def evaluate(
        self,
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        rubric: str,
        reference_behavior: str,
        ground_truth: Optional[dict[str, Any]] = None,
    ) -> JudgeVerdict:
        try:
            client = self._client()
            kwargs: dict[str, Any] = {}
            if _model_accepts_temperature(self.model):
                kwargs["temperature"] = 0
            last_exc: Optional[Exception] = None
            for _attempt in range(2):  # retry once if output is malformed
                response = client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    system=JUDGE_SYSTEM_PROMPT,
                    messages=[
                        {
                            "role": "user",
                            "content": _judge_user_prompt(
                                input, output, rubric, reference_behavior, ground_truth
                            ),
                        }
                    ],
                    output_config={"format": {"type": "json_schema", "schema": _JUDGE_SCHEMA}},
                    **kwargs,
                )
                if response.stop_reason == "refusal":
                    return _error_verdict(self.name, RuntimeError("model refused the request"))
                text = next((b.text for b in response.content if b.type == "text"), "")
                try:
                    return _coerce_verdict(text)
                except Exception as exc:  # bad json — try again
                    last_exc = exc
            return _error_verdict(self.name, last_exc or RuntimeError("malformed judge output"))
        except Exception as exc:
            return _error_verdict(self.name, exc)


class BedrockJudge(AnthropicJudge):
    """aws bedrock provider. same request shape as anthropic direct, just with
    `anthropic.`-prefixed model ids. the factory falls back to anthropic direct
    or mock if bedrock isn't set up."""

    name = "bedrock"

    def __init__(self, model: Optional[str] = None) -> None:
        super().__init__(model or config.BEDROCK_MODEL_ID)

    def _client(self):  # pragma: no cover - requires AWS credentials
        from anthropic import AnthropicBedrock

        kwargs: dict[str, Any] = {
            "timeout": config.EXTERNAL_TIMEOUT_S,
            "max_retries": config.EXTERNAL_RETRIES,
        }
        if config.AWS_REGION:
            kwargs["aws_region"] = config.AWS_REGION
        return AnthropicBedrock(**kwargs)


class OpenAIJudge(Judge):
    name = "openai"

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or (config.JUDGE_MODEL if "gpt" in config.JUDGE_MODEL else "gpt-4o")

    def evaluate(
        self,
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        rubric: str,
        reference_behavior: str,
        ground_truth: Optional[dict[str, Any]] = None,
    ) -> JudgeVerdict:
        try:
            import httpx

            payload = {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _judge_user_prompt(
                            input, output, rubric, reference_behavior, ground_truth
                        ),
                    },
                ],
            }
            last_exc: Optional[Exception] = None
            for _attempt in range(2):
                resp = httpx.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                    json=payload,
                    timeout=config.EXTERNAL_TIMEOUT_S,
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
                try:
                    return _coerce_verdict(text)
                except Exception as exc:
                    last_exc = exc
            return _error_verdict(self.name, last_exc or RuntimeError("malformed judge output"))
        except Exception as exc:
            return _error_verdict(self.name, exc)
