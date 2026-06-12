# HANDOFF.md — Agent takeover brief (written 2026-06-12)

> You are a coding agent taking over this project mid-build. Read this file, then
> `MEMORY.md` (architecture decisions + changelog), then `RECOIL_SENTINEL_PLAN.md`
> (the locked hackathon plan). Those three files are the complete context.

## What this project is

Two products in one repo, sharing one engine:

1. **Recoil** (original, COMPLETE) — "CI/CD for AI agents": trace capture → LLM-judge →
   freeze failures into eval cases → regression gate that blocks publishes (exit 1).
   Python engine + FastAPI (port 8787, SSE gate streaming) + Next.js dashboard (port 3000).
   Fully working with a seeded triage-agent demo (`recoil demo-check` proves it).

2. **Recoil Sentinel** (the HACKATHON pivot, Phases A+F done) — a REAL autonomous
   crypto-intel agent: fetches live ground truth (CoinGecko + DefiLlama, keyless),
   generates a cited report with a real Anthropic call, **machine-verifies every numeric
   claim against the sources**, publishes `cited.md` only on PASS, **freezes failures as
   regression cases and replays them before every future publish** (BLOCK on regression).

The hackathon ("Context Engineering Challenge — agents that act on the web") requires:
autonomous web action, ground truth, 3+ sponsor tools, publish to cited.md, monetization
via x402, public GitHub repo, 3-min demo. Judged 20% each: Idea / Technical / Tool Use /
Presentation / Autonomy. **Locked choices:** crypto intel · x402 · Airbyte + ClickHouse +
Composio · Render deploy.

## Current state (everything below is VERIFIED working)

- `pytest -q` → **22/22** (8 gate-logic, 6 seeded e2e, 8 sentinel verifier/gate).
- `recoil demo-check` → PASSED (original demo intact).
- `recoil sentinel` → ran LIVE twice: 20 live metrics → claude-sonnet-4-6 (~$0.024/run,
  ~25s) → 16/16 then 19/19 claims verified → cited.md published, exit 0.
- API endpoints verified: `/cited.md`, `/api/sentinel/status`, `/api/sentinel/latest`,
  plus all original dashboard APIs + SSE `/api/gate/stream`.
- `next build` clean (web/ dashboard, 7 routes).
- `render.yaml` blueprint written (web service + 6-hourly cron, shared /data disk) —
  **not yet deployed** (needs the user's Render account + GitHub repo).

## Environment facts (this machine)

- Windows 11, PowerShell primary. **No `uv`, no `pnpm`, no `make`** — use `.venv` + `npm`.
- Python 3.14 venv at `.venv` (`.venv\Scripts\python`, `.venv\Scripts\recoil`).
- `anthropic` SDK installed in the venv. Web deps installed in `web/node_modules`.
- **`.env` (gitignored) holds the real `ANTHROPIC_API_KEY`** — loaded by the minimal
  dotenv loader in `recoil/config.py`. The key was once pasted into `.env.example`
  (committed file) — **it must be ROTATED before the repo goes public.** `.env.example`
  now has a placeholder; keep it that way.
- Ports pinned: API 8787, web 3000. Kill strays:
  `Get-NetTCPConnection -LocalPort 8787 -State Listen | % { Stop-Process -Id $_.OwningProcess -Force }`

## Key commands

```powershell
.\.venv\Scripts\recoil sentinel              # one autonomous cycle (live, ~$0.025)
.\.venv\Scripts\recoil sentinel --watch 3600 # autonomy loop, hourly
.\.venv\Scripts\recoil demo-check            # original demo still healthy?
.\.venv\Scripts\python -m pytest -q          # full suite (no model calls)
.\.venv\Scripts\python -m uvicorn server.main:app --port 8787   # API
cd web; npm run dev                          # dashboard on :3000
```

## Where things live (sentinel-specific)

- `recoil/sentinel/sources.py` — live fetchers. API shapes were verified against the LIVE
  endpoints (not docs). DefiLlama `/protocols` includes CEXes — categories
  CEX/Chain/Bridge/RWA are filtered out. All sources down ⇒ `SourceError` (agent never
  runs blind); partial outage ⇒ proceeds with warning.
- `recoil/sentinel/agent.py` — `generate_report()` (live `messages.parse` →
  `IntelReport`; NO mock fallback by design) and `verify_report()` (deterministic: 1%
  relative tolerance on echoed values; unknown metric key = hallucinated source = fail).
- `recoil/sentinel/publish.py` — `render_cited_md()` (deterministic footnote citations
  from the snapshot), `publish_report()` (writes cited.md + .json sidecar ONLY on PASS;
  always captures the run as a trace under agent version `sentinel_v1`).
  `CITED_MD_PATH` overridable via `RECOIL_CITED_PATH` (Render uses /data/cited.md).
- `recoil/sentinel/gate.py` — Phase F. `freeze_failure()` (failed report → permanent
  eval case with FROZEN snapshot), `replay_frozen_cases(generate=…)` (re-runs the agent
  on frozen snapshots before publishing; previously-fixed case failing again = REGRESSION
  = BLOCK; `generate` injectable for tests). Replay limit default 3 (cost control).
- CLI: `sentinel` command in `recoil/cli.py` → `_sentinel_once()` (step 0 = replay gate,
  steps 1-4 = fetch/generate/verify/publish; returns exit code) + `--watch N` loop.
- Server: sentinel endpoints near the bottom of `server/main.py`.

## Gotchas (will bite you if unknown)

1. **`recoil reset --demo` and `recoil demo-check` DROP ALL TABLES** — they erase
   Sentinel run history and frozen sentinel cases. If durable sentinel history matters,
   separate the DBs or exclude sentinel data from reset.
2. The replay gate costs one live model call per frozen case per publish. Limit is 3.
3. `temperature` is REJECTED by Opus 4.7+/Fable models — `_model_accepts_temperature()`
   in `recoil/judge/llm_judges.py` handles this; don't add temperature blindly.
4. Sentinel triage-demo coexistence: sentinel eval cases are distinguished by
   `input.kind == "sentinel_replay"`; the original gate (`recoil gate`) runs ALL active
   cases, so a frozen sentinel case would enter the triage gate too — harmless today
   (demo-check resets first) but consider filtering by kind if it causes noise.
5. Windows PowerShell 5.1: no `&&`; loader scripts already handle this — see scripts/.

## UPDATE (later 2026-06-12): Phases B/C/D/E are DONE and live-verified

`recoil/sentinel/integrations.py` + x402 middleware in `server/main.py`. All four
sponsor integrations run REAL and were individually live-tested (see MEMORY.md entry
"Phases B+C+D+E SHIPPED" for the exact verified behavior and SDK gotchas: x402 needs
the [evm] extra; Composio args are positional + needs version-skip flag + user_id must
match the connection's entity; ClickHouse Cloud idles and times out on first wake).
The full pipeline fired live: report published, ClickHouse row inserted, GitHub issue
#2 opened autonomously, Airbyte authenticated, premium endpoint returns HTTP 402.

**Genuinely remaining:**
- Phase G: deploy via render.yaml (user clicks New → Blueprint, sets the sync:false
  env vars from .env in the Render dashboard), then verify
  https://<service>.onrender.com/cited.md and the 6-hourly cron.
- Optional: an Airbyte connection in the user's workspace (UI task) so
  airbyte_ground_truth_check reports connections + can trigger syncs.
- Optional: paying-client demo for x402 (x402 Python client + testnet USDC from a
  Base Sepolia faucet) to show the full 402 → pay → unlock loop on stage.
- Submission: 3-min demo recording + Devpost.

## Original phase plan (historical — B-E now complete)

Each needs credentials from the user — ASK for them before building; verify every
external API against current docs before coding (project rule):

- **Phase E — x402 paywall** (HIGHEST RISK, hackathon hard requirement "monetize"):
  gate `/api/sentinel/latest` (premium JSON) behind HTTP 402 per the x402 spec
  (Coinbase). Needs Base wallet + CDP api key. Verify current spec/facilitator first.
- **Phase D — Composio action**: on successful publish, autonomously open a GitHub
  issue / Slack post with the report summary + link. Needs Composio API key + connected
  account. Wire into `_sentinel_once()` after the publish step, behind graceful failure.
- **Phase B — Airbyte ground truth**: sync a real connector into the ground-truth store;
  judge/verifier reads from it (strengthens the "Conquer with Context" prize).
- **Phase C — ClickHouse**: mirror runs/eval_results/gate events to ClickHouse Cloud;
  point a dashboard panel at it. Keep SQLite as the local default (graceful degradation).
- **Phase G — deploy**: push to a public GitHub repo (ROTATE THE KEY FIRST), deploy via
  `render.yaml` blueprint, set ANTHROPIC_API_KEY in the Render dashboard, confirm the
  cron fires and `https://<service>.onrender.com/cited.md` serves the report.
- **Submission**: 3-min demo recording (script in RECOIL_SENTINEL_PLAN.md §demo),
  Devpost details, public repo link.

## Working agreements (the user's standing instructions)

- Update **MEMORY.md** (top of changelog, dated entry) after every meaningful change.
- Production-grade only: typed, graceful failures, no mock on the Sentinel demo path.
- Verify-before-integrate for every external API.
- The user is non-expert: explain in plain words, give exact copy-paste PowerShell
  commands, anticipate port-in-use errors (orphaned processes happen often here).
