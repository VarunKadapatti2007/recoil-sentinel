"""Judge selection + verdict cache keying.

Provider chosen by RECOIL_JUDGE_PROVIDER. Anything unconfigured (missing key,
missing SDK) degrades to the deterministic grounded mock judge with a loud log
— an optional service must never block the build or the demo.
"""

from __future__ import annotations

import hashlib
import json
import logging

from .. import config
from .base import Judge
from .mock_judge import MockJudge

log = logging.getLogger("recoil.judge")

_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        log.warning(message)


def output_hash(output: dict) -> str:
    """Stable hash of an agent output — the cache key component."""
    return hashlib.sha256(
        json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def get_judge(provider: str | None = None) -> Judge:
    name = (provider or config.JUDGE_PROVIDER).strip().lower()

    if name == "mock":
        return MockJudge()

    if name == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            _warn_once("ANTHROPIC_API_KEY not set — degrading judge to deterministic mock")
            return MockJudge()
        try:
            from .llm_judges import AnthropicJudge

            return AnthropicJudge()
        except ImportError:
            _warn_once("anthropic SDK not installed — degrading judge to deterministic mock")
            return MockJudge()

    if name == "bedrock":
        try:
            from .llm_judges import BedrockJudge

            import anthropic  # noqa: F401 — verify SDK present

            return BedrockJudge()
        except ImportError:
            _warn_once("anthropic[bedrock] not installed — trying Anthropic direct")
            return get_judge("anthropic")

    if name == "openai":
        if not config.OPENAI_API_KEY:
            _warn_once("OPENAI_API_KEY not set — degrading judge to deterministic mock")
            return MockJudge()
        from .llm_judges import OpenAIJudge

        return OpenAIJudge()

    log.warning("unknown judge provider %r — using mock", name)
    return MockJudge()
