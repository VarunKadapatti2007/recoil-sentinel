"""`recoil doctor` — trustworthy green/red readiness checklist.

The presenter runs this immediately before going on stage; every check is
real (no decorative greens) and every external probe has a fast timeout.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from typing import Callable

from . import config, db

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _mark(ok: bool, *, warn: bool = False) -> str:
    if ok:
        return f"{GREEN}[ ok ]{RESET}"
    return f"{YELLOW}[warn]{RESET}" if warn else f"{RED}[FAIL]{RESET}"


def run_doctor() -> bool:
    checks: list[tuple[str, bool, bool, str]] = []  # (name, ok, optional, detail)

    def add(name: str, fn: Callable[[], tuple[bool, str]], *, optional: bool = False) -> None:
        try:
            ok, detail = fn()
        except Exception as exc:  # a doctor check must never crash the doctor
            ok, detail = False, f"check crashed: {exc}"
        checks.append((name, ok, optional, detail))

    # --- core ---------------------------------------------------------------
    add("python >= 3.11", lambda: (sys.version_info >= (3, 11), sys.version.split()[0]))

    def deps() -> tuple[bool, str]:
        missing = [
            m
            for m in ("pydantic", "typer", "fastapi", "uvicorn", "httpx")
            if importlib.util.find_spec(m) is None
        ]
        return (not missing, "all installed" if not missing else f"missing: {', '.join(missing)}")

    add("python dependencies", deps)

    def db_ok() -> tuple[bool, str]:
        if not config.DB_PATH.exists():
            return False, f"{config.DB_PATH} missing — run `recoil reset --demo`"
        conn = db.connect()
        db.init_db(conn)
        runs = db.count_runs(conn)
        cases = len(db.list_eval_cases(conn, status="active"))
        published = db.get_published_version(conn)
        ok = runs >= 200 and cases >= 12 and published is not None
        return ok, f"{runs} runs, {cases} active cases, published: {published['label'] if published else 'NONE'}"

    add("database migrated + seeded", db_ok)

    def demo_versions() -> tuple[bool, str]:
        conn = db.connect()
        db.init_db(conn)
        labels = {v["label"] for v in db.list_versions(conn)}
        need = {"v_good", "v_regressed", "v_fixed"}
        missing = need - labels
        return (not missing, "v_good / v_regressed / v_fixed present" if not missing else f"missing {missing}")

    add("demo versions present", demo_versions)

    def cache_warm() -> tuple[bool, str]:
        conn = db.connect()
        db.init_db(conn)
        cases = db.list_eval_cases(conn, status="active")
        for label in ("v_good", "v_regressed", "v_fixed"):
            v = db.get_version_by_label(conn, label)
            if v is None:
                return False, f"version {label} missing"
            covered = sum(
                1 for c in cases if db.get_cached_result(conn, c["id"], v["id"]) is not None
            )
            if covered < len(cases):
                return False, f"{label}: {covered}/{len(cases)} verdicts cached"
        return True, "all demo verdicts cached (airplane-mode safe)"

    add("judge cache pre-warmed", cache_warm)

    add(
        "demo mode",
        lambda: (
            True,
            "ON — gate serves cached verdicts" if config.DEMO_MODE else "OFF — gate judges live",
        ),
    )

    # --- providers (optional enrichment) -------------------------------------
    def anthropic_probe() -> tuple[bool, str]:
        if not config.ANTHROPIC_API_KEY:
            return False, "ANTHROPIC_API_KEY not set — judge degrades to deterministic mock"
        if importlib.util.find_spec("anthropic") is None:
            return False, "anthropic SDK not installed (pip install anthropic)"
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=5.0, max_retries=0)
        try:
            client.models.retrieve(config.JUDGE_MODEL)
            return True, f"reachable, model {config.JUDGE_MODEL} ok"
        except Exception as exc:
            return False, f"unreachable ({type(exc).__name__})"

    if config.JUDGE_PROVIDER in ("anthropic", "bedrock"):
        add(f"judge provider ({config.JUDGE_PROVIDER})", anthropic_probe, optional=True)
    elif config.JUDGE_PROVIDER == "mock":
        add("judge provider (mock)", lambda: (True, "deterministic grounded judge"))

    def voice_check() -> tuple[bool, str]:
        from .voice import verdict_audio_path

        have = [v for v in ("BLOCK", "PASS") if verdict_audio_path(v).exists()]
        if len(have) == 2:
            return True, "both verdict MP3s pre-rendered"
        if config.ELEVENLABS_API_KEY:
            return False, f"key set but only {have or 'none'} rendered — run `recoil seed`"
        return False, "no key, no cached audio — voice layer silently disabled"

    add("voice verdicts", voice_check, optional=True)

    def web_check() -> tuple[bool, str]:
        node = shutil.which("node")
        if node is None:
            return False, "node not found — dashboard cannot run"
        web_dir = config.REPO_ROOT / "web"
        if not (web_dir / "node_modules").exists():
            return False, "web/node_modules missing — run `npm install` in web/"
        return True, "node + web deps installed"

    add("dashboard prerequisites", web_check, optional=True)

    # --- report ---------------------------------------------------------------
    print()
    print(f"{BOLD}recoil doctor{RESET}")
    print("-" * 72)
    required_ok = True
    for name, ok, optional, detail in checks:
        print(f" {_mark(ok, warn=optional)} {name:<34} {detail}")
        if not ok and not optional:
            required_ok = False
    print("-" * 72)
    if required_ok:
        print(f" {BOLD}{GREEN}READY{RESET}{BOLD} — the demo path is green.{RESET}")
    else:
        print(f" {BOLD}{RED}NOT READY{RESET}{BOLD} — fix the [FAIL] lines above before demoing.{RESET}")
    print()
    return required_ok
