#!/usr/bin/env bash
# One-command live demo orchestration:
#   reset to pristine demo state -> doctor must be green -> start API + web ->
#   print the exact on-stage runbook.
set -euo pipefail

cd "$(dirname "$0")/.."

PY=".venv/Scripts/python"
[ -f "$PY" ] || PY=".venv/bin/python"
[ -f "$PY" ] || PY="python"

echo "[recoil] restoring pristine demo state..."
"$PY" -m recoil.cli reset --demo

echo "[recoil] running doctor..."
if ! "$PY" -m recoil.cli doctor; then
  echo "[recoil] doctor is NOT READY — fix the failures above before demoing." >&2
  exit 1
fi

cleanup() {
  echo
  echo "[recoil] shutting down..."
  kill "${API_PID:-0}" "${WEB_PID:-0}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[recoil] starting API on :8787..."
"$PY" -m uvicorn server.main:app --port 8787 --log-level warning 2>&1 | sed 's/^/[api] /' &
API_PID=$!

echo "[recoil] starting web on :3000..."
(cd web && npm run dev 2>&1 | sed 's/^/[web] /') &
WEB_PID=$!

sleep 3
cat <<'RUNBOOK'

============================================================================
 RECOIL DEMO RUNBOOK (rehearse this exact flow)
============================================================================
 0. Pre-stage:  `recoil demo-check` must print PASSED. Doctor must be READY.
 1. Open http://localhost:3000  -> Overview: 250 runs, 12 frozen cases,
    last gate PASS, published v_good. "This is a real agent in production."
 2. Traces -> click any run -> show the span waterfall (tokens/latency/cost).
 3. "I want my agent to be more concise." Top bar: candidate = v_regressed.
    Press RUN GATE. Cases tick green... then the after-hours outage case
    SNAPS RED. Verdict: BLOCK. Publish refused (exit 1 from the CLI too).
 4. Click "Open regression diff": escalate true -> false, on_call_paged
    true -> false, highlighted. Read the judge's grounded rationale.
 5. "Here's the fix." Top bar: candidate = v_fixed. RUN GATE again.
    12/12 green. Verdict: PASS. Press "Publish v_fixed" -> published.
 6. Optional: "Send test alert" -> after-hours outage -> a live run appears
    in Traces, judged in real time.
 7. Close: "Every failure becomes a permanent test. Nothing regresses twice."
============================================================================
 Ctrl-C stops API + web together.
RUNBOOK

wait
