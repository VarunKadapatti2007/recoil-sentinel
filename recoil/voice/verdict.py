"""Optional spoken verdicts via ElevenLabs, with pre-rendered MP3 fallback.

The demo never waits on this layer:
- Verdict MP3s are pre-rendered during seeding when ELEVENLABS_API_KEY is set.
- At gate time, the cached file is served; live generation only happens if a
  cached file is missing AND a key is present, bounded by a short timeout.
- With no key and no cached audio, the layer silently no-ops.

API shape (current ElevenLabs REST):
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
    """Call ElevenLabs TTS. Returns True on success; never raises."""
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
    """Pre-render both verdict lines to MP3 (seeding step). No-op without a key."""
    results = {}
    for verdict, line in VERDICT_LINES.items():
        path = verdict_audio_path(verdict)
        if path.exists():
            results[verdict] = True
            continue
        results[verdict] = _generate_mp3(line, path)
    return results


def speak_verdict(verdict: str) -> Optional[Path]:
    """Return the path of the verdict MP3 to play, or None if voice is unavailable.
    Prefers the pre-rendered cache; tries one fast live generation otherwise."""
    verdict = verdict.upper()
    if verdict not in VERDICT_LINES:
        return None
    path = verdict_audio_path(verdict)
    if path.exists():
        return path
    if _generate_mp3(VERDICT_LINES[verdict], path, timeout=5.0):
        return path
    return None
