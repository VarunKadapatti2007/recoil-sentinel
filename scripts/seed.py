"""thin wrapper to seed the db — just run `python scripts/seed.py`."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recoil import config, db  # noqa: E402
from recoil.seeding import seed_all  # noqa: E402


def main() -> None:
    config.ensure_dirs()
    conn = db.reset_db()
    summary = seed_all(conn, verbose=True)
    print(
        f"seeded: {summary['runs']} runs, {len(summary['cases'])} frozen cases, "
        f"{len(summary['versions'])} versions, published baseline v_good"
    )
    audio = summary.get("audio", {})
    if any(audio.values()):
        print(f"voice verdicts pre-rendered: {audio}")
    else:
        print("voice verdicts skipped (no ELEVENLABS_API_KEY) — voice layer degrades silently")


if __name__ == "__main__":
    main()
