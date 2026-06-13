"""optional spoken verdicts via elevenlabs, with a pre-rendered mp3 fallback.

the demo never waits on this layer:
- verdict mp3s are pre-rendered during seeding when ELEVENLABS_API_KEY is set.
- at gate time we serve the cached file; live generation only happens if the
  cached file is missing and a key is present, capped by a short timeout.
- with no key and no cached audio, this layer just no-ops.

api shape (current elevenlabs rest):
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
headers: xi-api-key; body: {"text": ..., "model_id": "eleven_turbo_v2_5"}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .. import config

log = logging.getLogger("recoil.voice")

VERDICT_LINES = {
    "BLOCK": (
        "Hold on — this update regressed the after-hours escalation case you fixed "
        "last week. Don't ship."
    ),
    "PASS": "Cleared. Suite is green. Shipping.",
}


def verdict_audio_path(verdict: str) -> Path:
    return config.AUDIO_DIR / f"verdict_{verdict.lower()}.mp3"


def _generate_mp3(text: str, out_path: Path, *, timeout: Optional[float] = None) -> bool:
    """call elevenlabs tts. returns true on success; never raises."""
    if not config.ELEVENLABS_API_KEY:
        return False
    try:
        import httpx

        resp = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            json={"text": text, "model_id": "eleven_turbo_v2_5"},
            timeout=timeout or config.EXTERNAL_TIMEOUT_S,
        )
        resp.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        return True
    except Exception as exc:
        log.warning("elevenlabs generation failed (%s) — voice layer degrades silently", exc)
        return False


def prerender_verdicts() -> dict[str, bool]:
    """pre-render both verdict lines to mp3 (seeding step). no-op without a key."""
    results = {}
    for verdict, line in VERDICT_LINES.items():
        path = verdict_audio_path(verdict)
        if path.exists():
            results[verdict] = True
            continue
        results[verdict] = _generate_mp3(line, path)
    return results


def speak_verdict(verdict: str) -> Optional[Path]:
    """return the path of the verdict mp3 to play, or none if voice is unavailable.
    prefers the cached file; otherwise tries one fast live generation."""
    verdict = verdict.upper()
    if verdict not in VERDICT_LINES:
        return None
    path = verdict_audio_path(verdict)
    if path.exists():
        return path
    if _generate_mp3(VERDICT_LINES[verdict], path, timeout=5.0):
        return path
    return None
