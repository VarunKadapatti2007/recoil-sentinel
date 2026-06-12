"""Central configuration. Every knob is an environment variable; everything has a safe default.

The core invariant: with no env vars set at all, Recoil runs fully offline
(mock judge, mock agent, demo mode on).
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency): KEY=VALUE lines, # comments,
    real environment always wins over file values."""
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass  # unreadable .env must never break startup


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RECOIL_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("RECOIL_DB_PATH", DATA_DIR / "recoil.db"))
AUDIO_DIR = DATA_DIR / "audio"
FROZEN_EVALS_DIR = DATA_DIR / "frozen_evals"

# --- Judge ---------------------------------------------------------------
# anthropic | bedrock | openai | mock. Anything unconfigured degrades to mock.
JUDGE_PROVIDER = os.environ.get("RECOIL_JUDGE_PROVIDER", "anthropic").strip().lower()
JUDGE_MODEL = os.environ.get("RECOIL_JUDGE_MODEL", "claude-opus-4-8")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
BEDROCK_MODEL_ID = os.environ.get("RECOIL_BEDROCK_MODEL_ID", "anthropic.claude-opus-4-8")
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", ""))

# --- Demo determinism -----------------------------------------------------
# In demo mode the gate serves real, previously computed judge verdicts from
# cache so the live demo never depends on network/model variance.
DEMO_MODE = _env_bool("RECOIL_DEMO_MODE", True)

# --- Agent under test -----------------------------------------------------
AGENT_MODEL = os.environ.get("RECOIL_AGENT_MODEL", "claude-sonnet-4-6")

# --- Voice (optional) -----------------------------------------------------
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

# --- Sentinel sponsor integrations (all optional; graceful no-ops if unset) -
# x402 paywall (Coinbase HTTP-402): premium report endpoint
X402_WALLET_ADDRESS = os.environ.get("X402_WALLET_ADDRESS", "")
X402_NETWORK = os.environ.get("X402_NETWORK", "base-sepolia")
X402_PRICE = os.environ.get("X402_PRICE", "$0.01")
X402_FACILITATOR_URL = os.environ.get("X402_FACILITATOR_URL", "https://x402.org/facilitator")

# Composio: real web actions (GitHub issue on publish)
COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
COMPOSIO_USER_ID = os.environ.get("COMPOSIO_USER_ID", "default")
COMPOSIO_CONNECTED_ACCOUNT_ID = os.environ.get("COMPOSIO_CONNECTED_ACCOUNT_ID", "")
COMPOSIO_GITHUB_OWNER = os.environ.get("COMPOSIO_GITHUB_OWNER", "VarunKadapatti2007")
COMPOSIO_GITHUB_REPO = os.environ.get("COMPOSIO_GITHUB_REPO", "recoil-sentinel")

# ClickHouse Cloud: run/event analytics store
CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST", "")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")

# Airbyte: ground-truth ingestion control plane
AIRBYTE_CLIENT_ID = os.environ.get("AIRBYTE_CLIENT_ID", "")
AIRBYTE_CLIENT_SECRET = os.environ.get("AIRBYTE_CLIENT_SECRET", "")
AIRBYTE_WORKSPACE_ID = os.environ.get("AIRBYTE_WORKSPACE_ID", "")

# --- Ports (pinned — never auto-random, see brief §13a) --------------------
API_PORT = int(os.environ.get("RECOIL_API_PORT", "8787"))
WEB_PORT = int(os.environ.get("RECOIL_WEB_PORT", "3000"))
WEB_ORIGIN = os.environ.get("RECOIL_WEB_ORIGIN", f"http://localhost:{WEB_PORT}")

# --- External call hygiene -------------------------------------------------
EXTERNAL_TIMEOUT_S = float(os.environ.get("RECOIL_EXTERNAL_TIMEOUT_S", "20"))
EXTERNAL_RETRIES = int(os.environ.get("RECOIL_EXTERNAL_RETRIES", "2"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    FROZEN_EVALS_DIR.mkdir(parents=True, exist_ok=True)
