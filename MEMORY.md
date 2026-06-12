# MEMORY.md — Recoil changelog & long-term context

> Living memory for this codebase. Every meaningful change lands here as a dated entry:
> what changed, why, and any decision a future contributor (human or AI) needs to know.
> Newest entries first. Keep entries factual and terse; link files, not feelings.

---

## How to use this file

- **Before changing anything**, skim "Architecture decisions" below — they explain the
  non-obvious choices so you don't accidentally undo one.
- **After any change**, add an entry at the top of the changelog: date, scope, what/why.
- Demo invariants that must never break are marked **[DEMO-CRITICAL]**.

---

## Architecture decisions (the why behind the code)

1. **stdlib `sqlite3` + thin DAL, no ORM** (`recoil/db.py`). Reliability over cleverness on
   the demo path; every query is explicit and debuggable. `check_same_thread=False` is set
   because the SSE stream judges cases via `asyncio.to_thread` — access is sequential per
   connection, never concurrent.
2. **Deterministic behavior profiles instead of live LLM calls by default**
   (`recoil/agent/versions.py`). Each agent version has a pure function that produces exactly
   the output its system prompt would elicit. This makes seeding reproducible and the demo
   network-free. The live Anthropic path exists (`triage.py`) and falls back to mock on any error.
3. **The verdict cache IS `eval_results`** keyed `(eval_case_id, agent_version_id, output_hash)`.
   `RECOIL_DEMO_MODE=true` (default) makes the gate read cache-first. **[DEMO-CRITICAL]**
   Seeding pre-warms verdicts for v_good / v_regressed / v_fixed × all 12 cases.
4. **Gate logic is a pure function** (`classify_cases` in `recoil/gate/engine.py`) so the
   regression rules are directly unit-testable: regression = baseline-pass AND candidate-fail;
   BLOCK iff any regression; newly-fixed counted, never blocking. **[DEMO-CRITICAL]**
5. **Judge degradation chain**: anthropic → (no key/SDK) → deterministic grounded mock,
   with warn-once logging. A judge provider must NEVER raise on the demo path — provider
   errors return a conservative `passed=false` verdict naming the error.
6. **Model facts verified at build time (2026-06-12)**: judge default `claude-opus-4-8`;
   `temperature` is rejected on Opus 4.7+/Fable models, so `_model_accepts_temperature()`
   gates it; Bedrock ids carry the `anthropic.` prefix (`anthropic.claude-opus-4-8`).
7. **Airbyte / Guild are interface-ready, not wired** (`recoil/adapters/`). Their current SDKs
   weren't verifiable at build time; per the brief, they're clean interfaces with working local
   defaults (JSON ground-truth store, local publish target) and explicit errors if selected
   unconfigured. Do not hardcode unverified SDK calls.
8. **Ports pinned**: API 8787, web 3000. Never auto-random — the presenter's muscle memory
   and pre-opened tabs depend on it. **[DEMO-CRITICAL]**
9. **Toolchain deviation from the brief**: `uv` and `pnpm` are not on this machine, so the
   build uses stdlib `venv` + `npm`. Nothing depends on the package manager.
10. **No Google-font downloads** in the web app (system font stack with Inter/JetBrains Mono
    preferred if installed) — the dashboard must build and run in airplane mode.
11. **Seeded story line** (must stay consistent): v1 → v2 → **v_good (published)** →
    v_regressed / v_fixed (both children of v_good). 12 frozen cases, each promoted from a
    real seeded failure run via the actual promotion pipeline (not inserted by hand).
    v_regressed fails exactly 2 cases (the after-hours hero + the partial eu-west-1 outage,
    both after-hours outages — that's the "broke the after-hours class" story). v_fixed
    passes 12/12. **[DEMO-CRITICAL]**

## Demo invariants (assert with `recoil demo-check`)

- `recoil gate --candidate v_regressed` → **BLOCK**, exit 1, hero case in the regression list.
- `recoil gate --candidate v_fixed` → **PASS**, exit 0.
- Both run entirely from cache with networking disabled.
- `recoil reset --demo` restores all of the above in < 2s, idempotently.

---

## Changelog

### 2026-06-12 — REAL cited.md publishing via Senso (eligibility requirement)

DISCOVERY: "cited.md" in the hackathon is a REAL platform (cited.md, powered by Senso.ai —
also a sponsor), NOT just a repo file. Publishing a local cited.md file does NOT satisfy the
"publish your agent's output to cited.md" requirement. Verified the Senso API from docs/search:
POST https://sdk.senso.ai/api/v1/content/raw, header X-API-Key, body {title, summary, text},
returns 202 with id. Built `senso_publish_citeable()` in integrations.py — fires only AFTER a
report PASSES verification (cited.md only receives machine-verified content). Wired into both
the CLI [5/5] block and POST /api/sentinel/run (integrations.senso_cited_md). Config:
SENSO_API_KEY + SENSO_API_BASE; added to .env/.env.example/render.yaml. Graceful no-op without
key (verified). pytest 22/22.
ACTION REQUIRED (user): get a SENSO_API_KEY at senso.ai/docs.senso.ai, put it in .env (and
Render dashboard), then do ONE live `recoil sentinel` run to confirm a real 202 + content id
(the end-to-end publish to cited.md could NOT be confirmed without the key — the API
field names came from docs/search, not a verified live call; the code logs the raw Senso
response and degrades gracefully if a field differs). NOTE: also strengthens "Best Use of
Senso.ai" prize.

### 2026-06-12 — Verification Console UI (the presentation layer judges see)

New dashboard page `web/app/verify/page.tsx` (nav "Verify (live)") — a chat-style console
that makes the invisible mechanism VISIBLE: pick Market or Wallet, type an instruction/focus,
optional "inject a false claim" toggle, Run. Renders the full workflow: (1) ground-truth
facts (clickable to source), (2) the agent's claims, (3) a claim-by-claim verification table
(claimed vs ground truth, ✓ match / ✕ MISMATCH), (4) PASS→published or BLOCK→refused+frozen
with the reason. Backed by enriched `/api/sentinel/run` and `/api/wallet/verify` (added shared
`_verification_view` returning ground_truth + findings + verification.checks; both now also
return domain/subject_label). New api.ts helpers runMarketVerification/runWalletVerification +
VerificationRun type. next build clean (/verify 4.44kB); pytest 22/22. This is the
"show judges exactly what's verified and why" surface the user asked for.

### 2026-06-12 — On-chain TRANSACTION INTEGRITY (Coinbase/Base wallet) — plug-and-play proof

The "plug and play in any domain" thesis proven: SAME engine (generate->verify->gate->
freeze), ground-truth source swapped from CoinGecko/DefiLlama to the BLOCKCHAIN via
keyless JSON-RPC.
- `recoil/sentinel/onchain.py`: `fetch_wallet_snapshot(address, network)` reads live
  ETH balance (eth_getBalance), nonce (eth_getTransactionCount), USDC balance (ERC-20
  balanceOf eth_call), chainId — returns the STANDARD snapshot shape so it flows through
  the existing generate_report/verify_report/tamper_report unchanged. Also
  `fetch_transaction_snapshot(tx_hash)` (verify a specific tx; missing tx = caught
  failure). Keyless Base RPC: sepolia.base.org / mainnet.base.org. USDC contracts +
  Basescan explorer links baked in.
- `recoil verify-wallet [--address --network --tamper]`: fetch chain -> agent claims ->
  verify EVERY claim vs chain -> publish wallet_integrity.md on PASS, BLOCK+freeze on
  mismatch. `POST /api/wallet/verify?tamper=` mirrors it for the deployed site/UI.
- VERIFIED LIVE against the user's real wallet (0xad6D…, base-sepolia, chain 84532,
  empty: 0 ETH/0 USDC/nonce 0): PASS path 7/7 claims grounded -> published; --tamper
  planted "1 ETH" -> verifier caught it vs chain's 0 -> BLOCKED, nothing published,
  frozen. exit 1. THIS is the transaction-integrity demo: an AI that can't lie about
  (or mis-send) money. Pairs with the x402/CDP rails already wired.
- pytest 22/22. Cleaned test-injected frozen case.

The product now spans THREE verification domains on one engine: market intel, on-chain
transaction integrity, and the original codebase/agent regression gate. That IS the
plug-and-play story for judges.

### 2026-06-12 — Demo-ability: --focus (customize) + --tamper (show the gate catch a lie)

Problem: every run PASSED, so judges never SAW the verification mechanism do anything.
Fix:
- `recoil sentinel --focus "<topic>"` (+ ?focus= on /api/sentinel/run): steers the agent's
  analysis to any slice (a chain, token, stablecoins, lending). User's innovation surface
  within crypto. VERIFIED: focus "Solana ecosystem" → focused report, 16/16, PASS.
- `recoil sentinel --tamper` (+ ?tamper=true): fault injection. `tamper_report(report,
  snapshot)` plants a false numeric claim against a REAL ground-truth metric (value*10+1,
  always outside tolerance) so verification is GUARANTEED to fail. VERIFIED: planted BTC
  635,501 vs real 63,550 → verifier flagged it → publication REFUSED → failure FROZEN as
  regression case → exit 1. cited.md untouched. THIS is the live demo of the internal
  mechanism (PASS path vs BLOCK path). Cleaned the test-injected frozen case afterward so
  the local DB starts clean.
- 3-act demo sequence: (1) `recoil sentinel` → PASS+publish; (2) `recoil sentinel --tamper`
  → BLOCK+freeze ("I made it lie, it caught itself"); (3) `recoil sentinel` again → step-0
  replay gate shows the frozen case being re-checked ("it remembers").
- pytest 22/22 still green.

### 2026-06-12 — DEPLOYED: live at https://recoil-api.onrender.com (Phase G COMPLETE)

Blueprint synced; the boot-time autonomous run fired ON RENDER and was verified from
outside: /api/health 200; /cited.md 200 serving a cloud-generated report (run 6ebe9b37,
11/11 claims verified); /api/sentinel/premium → HTTP 402 (paywall ACTIVE in prod);
/api/sentinel/status shows published+paywall+ClickHouse stats; GitHub issue #4 opened
autonomously from Render at 20:37 UTC. Next runs every 6h via the in-process scheduler.
Hardening: ClickHouse integration timeout raised to 60s (cloud run's insert missed due
to ClickHouse Cloud cold start — degraded gracefully as designed). All phases A-G done;
remaining: optional Airbyte connection, optional x402 paying-client demo, 3-min
recording + Devpost submission.

### 2026-06-12 — Phase G fix: Render cron can't mount disks → in-process scheduler

Render blueprint validation rejected the two-service layout ("disks not supported for
cron jobs"; Render disks are per-service anyway, never shared). Fix: ONE web service —
`server/main.py` now has a built-in scheduler (startup hook + daemon thread) that runs
the full sentinel cycle every `RECOIL_SENTINEL_INTERVAL_S` seconds (Render sets 21600;
min clamped to 300; first run fires at boot; loop survives any exception). render.yaml
rewritten to a single service. VERIFIED locally: server on :8788 with the env set ran
the whole pipeline autonomously in-process (20/20 claims, published, ClickHouse row 3,
GitHub issue #3) while the API stayed responsive mid-run. Unset env = scheduler off
(local default).

### 2026-06-12 — Phases B+C+D+E SHIPPED: all sponsor integrations LIVE-VERIFIED

**What:** `recoil/sentinel/integrations.py` + x402 middleware in `server/main.py`.
All four integrations are REAL (no mocks) and individually live-tested:
- **x402 (Phase E):** `pip install x402[fastapi,evm]` (evm extra REQUIRED or middleware
  refuses to register). `PaymentMiddlewareASGI` + `x402ResourceServer` + public testnet
  facilitator (https://x402.org/facilitator) guard `GET /api/sentinel/premium`
  ($0.01 USDC, base-sepolia = eip155:84532). VERIFIED: unpaid request → HTTP 402 with
  base64 payment requirements in the `payment-required` header (x402 protocol v2).
  Paywall activates only when X402_WALLET_ADDRESS set; failures never take the API down.
- **Composio (Phase D):** SDK `composio.tools.execute("GITHUB_CREATE_AN_ISSUE", args,
  user_id=…, connected_account_id=…, dangerously_skip_version_check=True)` — arguments
  POSITIONAL; version pin or skip-flag REQUIRED. The user's GitHub connection lives
  under entity `pg-test-d57ce657-…` with account `ca_3yNgnnjrLbgA` (both now in .env;
  user_id MUST match the connection's owner or error 1812). VERIFIED: real issues
  created autonomously — repo issues #1 (smoke) and #2 (live pipeline).
- **ClickHouse (Phase C):** HTTPS interface via httpx (no driver), `sentinel_runs`
  MergeTree table auto-created, JSONEachRow inserts, aggregate stats in
  /api/sentinel/status. GOTCHA: ClickHouse Cloud idles — first request after sleep can
  ReadTimeout; integration degrades gracefully and succeeds on retry. VERIFIED: live
  insert + count + stats roundtrip.
- **Airbyte (Phase B):** client-credentials token (POST /v1/applications/token), lists
  workspace connections, can trigger sync of the first connection. VERIFIED: live auth,
  workspace reachable (no connections configured yet — user can add one in Airbyte UI
  and it gets picked up automatically).

**Pipeline:** `recoil sentinel` step [5/5] now fires ClickHouse + Composio + Airbyte on
every successful publish (all graceful). New endpoint `GET /api/sentinel/premium`
(full report + verification evidence + snapshot) behind the paywall.

**Full live e2e VERIFIED:** 20 live metrics → claude-sonnet-4-6 report ($0.025) →
16/16 claims grounded → cited.md published → ClickHouse row 2 → GitHub issue #2
opened autonomously → Airbyte authenticated. pytest 22/22.

**Also:** pyproject `[sentinel]` extra (anthropic + x402[fastapi,evm] + composio);
render.yaml: buildCommand uses `.[sentinel]`, all sponsor env vars added (sync:false).

### 2026-06-12 — Repo public + full live verification with DEMO_MODE=false

- Pushed to public GitHub: https://github.com/VarunKadapatti2007/recoil-sentinel
  (initial commit verified secret-free; .env never staged). cited.md now has a public URL.
- ANTHROPIC key ROTATED by user (old exposed key dead). .env now holds all Phase B-E
  creds: CDP/x402 (base-sepolia), Composio, ClickHouse Cloud, Airbyte client_id+secret.
- RECOIL_DEMO_MODE=false verified end-to-end: `recoil gate --candidate v_regressed`
  judged LIVE by claude-opus-4-8 → same verdict as the deterministic judge (BLOCK,
  same 2 regressed cases, exit 1) — strong judge-agreement validation. pytest 22/22
  (tests pin mock judge, unaffected). doctor READY. Third live sentinel run: 19/19
  grounded, published, exit 0.
- NOTE: with demo mode off, every dashboard "Run gate" click = 12 live Opus judgments
  (~1-2 min, ~$0.2). For a stage demo of the triage flow, flip RECOIL_DEMO_MODE=true;
  Sentinel ignores this flag entirely (always live).
- User preference (standing): NO AI attribution in commits/PRs/docs.

### 2026-06-12 — Sentinel Phase F SHIPPED: regression gate over real reports + autonomy + Render blueprint

**What:**
- `recoil/sentinel/gate.py` — `freeze_failure()` freezes a verification-failed report as
  a permanent eval case (input = FROZEN snapshot, so replays are data-deterministic);
  `replay_frozen_cases(generate=…)` re-runs the agent on frozen snapshots before any
  publish: previously-fixed case failing again = REGRESSION = BLOCK; never-fixed still
  failing = reported, not blocking; newly passing = stamped fixed_in. Replay limit 3
  (one live model call each). `generate` injectable for tests; agent crash during
  replay reads as FAIL, never crashes the gate.
- CLI `recoil sentinel` now: step 0 replay gate (skippable `--skip-gate`) → fetch →
  generate → verify → publish; on verification failure the report is FROZEN before
  exit 1. Added `--watch N` autonomy loop (min 60s). Refactored into `_sentinel_once()`
  returning exit codes.
- Server: `GET /cited.md` (public artifact), `GET /api/sentinel/latest` (sidecar JSON),
  `GET /api/sentinel/status` (frozen-case count + recent runs).
- `render.yaml` — Render blueprint: web service (uvicorn) + 6-hourly cron
  (`recoil sentinel`), shared 1GB disk at /data, `RECOIL_CITED_PATH=/data/cited.md`
  (new env override in publish.py), ANTHROPIC_API_KEY sync:false. NOT yet deployed.
- `tests/test_sentinel_gate.py` — 8 tests (verifier tolerance/hallucination, freeze
  shape, fixed→regressed→BLOCK, never-fixed not blocking, crash-as-fail, empty gate).

**Verified:** pytest 22/22; second live sentinel run 19/19 claims → published exit 0;
all three new endpoints 200 via TestClient; demo-check still PASSED.

**Handoff:** `HANDOFF.md` created — complete takeover brief for the next coding agent
(state, env facts, commands, gotchas, remaining phases B/C/D/E/G in priority order).

### 2026-06-12 — Sentinel Phase A SHIPPED: real autonomous agent + cited.md (live path verified)

**What:** `recoil/sentinel/` package + `recoil sentinel` CLI command — the real (no-mock)
autonomous crypto-intel agent of RECOIL_SENTINEL_PLAN.md Phase A.
- `sources.py` — live keyless ground truth: CoinGecko simple/price + DefiLlama
  /protocols + /v2/chains (shapes verified against the live APIs, not docs; CEX/Chain/
  Bridge/RWA categories filtered out of "DeFi protocols"). Every metric carries its own
  source URL + fetch timestamp. Raises `SourceError` if all sources fail — the agent
  never runs blind.
- `agent.py` — REAL Anthropic call (`claude-sonnet-4-6`, `messages.parse` structured
  output → `IntelReport`: 3-5 findings, each must list `metric_keys` + echo
  `claimed_values`). Deliberately NO mock fallback (`SentinelError` instead) — Phase A
  is the live path. `verify_report()` deterministically grades every numeric claim
  against the snapshot (1% relative tolerance; unknown metric key = hallucinated source
  = fail).
- `publish.py` — gate semantics on publication: cited.md (+ .json sidecar) written ONLY
  if all claims verify; BLOCK → exit 1, cited.md untouched, run still recorded. Citations
  are attached deterministically from the snapshot (footnote per metric, resolvable URL).
  Whole run captured as a Recoil trace (fetch/llm/verify spans, real tokens + cost) under
  agent version `sentinel_v1`.

**Verified live (first run):** 20 live metrics in 945ms → claude-sonnet-4-6 report
(2511→1138 tok, $0.0246, ~28s) → **16/16 claims grounded** → cited.md published, exit 0.
Old suite still green (14/14 pytest, demo-check PASSED).

**Env/key handling:** user pasted a real ANTHROPIC key into `.env.example` (committed
file!) — moved to gitignored `.env`, placeholder restored, and a minimal no-dependency
`.env` loader added to `recoil/config.py` (real env always wins over file values).
**ROTATE THE KEY before the repo goes public** — it was exposed in a committed template.
`anthropic` SDK now installed in the venv.

**Known interaction:** `recoil reset --demo` / `recoil demo-check` DROP ALL TABLES and
reseed — they erase captured Sentinel runs. Fine for now; if Sentinel history must
survive, move triage-demo seeding to a separate DB or exclude `sentinel_*` versions
from reset.

**Next:** Phase B (Airbyte ground truth) → C (ClickHouse) → D (Composio action) →
E (x402 paywall) → F (gate over reports) → G (Render deploy). See RECOIL_SENTINEL_PLAN.md.

### 2026-06-12 — PIVOT: Recoil → "Recoil Sentinel" (hackathon fit)

**Why:** The actual hackathon is the "Context Engineering Challenge — agents that act on
the open web" (autonomous agent, real action, ground truth, 3+ sponsor tools, publish to
cited.md, monetize via payment rails; judged 20% each on Idea/Technical/Tool Use/
Presentation/Autonomy). Recoil-as-a-CI-gate does NOT satisfy the core theme or the hard
requirements (no web action, mock data, no sponsor tools live, no cited.md, no payments).

**Decision:** Invert the product. Build a **real autonomous crypto on-chain intelligence
agent** that publishes cited reports to `cited.md`, monetizes via **x402**, and is gated by
Recoil's existing regression engine (judge + promotion + gate) so it can't republish a
learned mistake. The acting agent is the star; Recoil's gate/self-growing memory is the
"Most Innovative Use of Agents" differentiator. Everything must run on REAL live data; the
recorded demo must show the real path succeeding (mock won't survive the Autonomy criterion).

**Locked stack (user-chosen):** domain = crypto/on-chain intel; payments = x402;
sponsor tools = Airbyte Agent Engine (ground truth) + ClickHouse (store/analytics) +
Composio (real web actions); deploy = Render. Anthropic for agent + judge.

**Reuse vs replace:** KEEP the gate (`gate/`), judge interface (`judge/`), promotion
(`evals/promotion.py`), models, dashboard shell. REPLACE the fake agent behavior profiles
with a real Anthropic agent + live crypto data; ADD cited.md publisher, Airbyte ingestion,
ClickHouse store, Composio action, x402 paywall, Render deploy.

**Plan of record:** see [RECOIL_SENTINEL_PLAN.md](RECOIL_SENTINEL_PLAN.md) — phased A→G with
per-phase acceptance criteria and the credentials checklist. Build credential-free spine
(Phase A) first; x402 is the highest-risk integration. Verify every external API against
current docs before coding (project principle #verify-before-integrate).

**Status:** plan locked; implementation not yet started. The v0.1.0 CI-gate build below
remains intact and is the engine the Sentinel reuses.

### 2026-06-12 — v0.1.0: initial production build (full system)

**Engine (Python package `recoil/`)**
- `db.py` — SQLite schema + DAL: `agent_versions`, `runs`, `eval_cases`, `eval_results`
  (unique verdict-cache key), `gate_runs`; WAL mode, indexes, dict rows.
- `models.py` — Pydantic contracts mirroring the schema + `JudgeVerdict`, `GateReport`,
  `TriageOutput` (the structured agent output: queue/priority/escalate/on_call_paged/reason).
- `agent/` — versioned incident-triage demo agent; 5 versions (v1, v2, v_good, v_regressed,
  v_fixed) with deterministic behavior profiles + optional live Anthropic path with
  structured output (`messages.parse`) and mock fallback; APM-style span simulation.
- `judge/` — provider-agnostic `Judge` interface; `MockJudge` (deterministic, grounded,
  field-weighted scoring, PII regex checks); `AnthropicJudge` (structured JSON via
  `output_config`, bounded malformed-output retry, refusal handling); `BedrockJudge`
  (AnthropicBedrock client); `OpenAIJudge` (JSON mode via httpx); warn-once degradation
  factory; `output_hash()` cache keying.
- `evals/` — failure→case promotion (snapshots input + ground truth + reference behavior,
  records `first_failed_version_id`, idempotent on identical input); suite runner with
  cache-first demo mode and `fixed_in_version_id` stamping.
- `gate/` — pure `classify_cases` + `run_gate` (resolves candidate/baseline, persists
  `gate_runs`, returns `GateReport`).
- `seeding.py` — 250 runs over 18 days across v1/v2/v_good with varied latencies
  (600–2400ms LLM spans), token counts, fractional-cent costs; 12 archetype cases promoted
  from real failure runs; verdict cache pre-warmed for all demo versions; one historical
  PASS gate run; local ground-truth JSON store; optional voice pre-render.
- `cli.py` — `gate` / `publish` / `run` / `reset --demo` / `demo-check` / `seed` /
  `install-hook` (git pre-push) / `doctor` / `serve`; monospace verdict table; exit codes
  1=BLOCK, 0=PASS, 2=operator error.
- `doctor.py` — readiness checklist (deps, DB seeded, demo versions, cache warm, provider
  probes with 5s timeout, voice, web deps) ending in READY / NOT READY.
- `voice/` — ElevenLabs TTS with pre-rendered MP3 cache; never blocks the demo.
- `adapters/` — ground-truth provider (local JSON default, Airbyte interface-ready) and
  publish target (local default, Guild interface-ready).

**API (`server/main.py`)**
- Read APIs: overview stats, runs list/detail, eval cases list/detail, field-by-field
  semantic diff endpoint, gate-run history, versions.
- `POST /api/runs` — "send test alert": real run → capture → judge → promote on FAIL.
- `POST /api/publish` — gate-then-publish.
- `GET /api/gate/stream` — SSE streaming gate run (start/case/verdict/error events,
  legible per-case pacing, optional publish-on-PASS).
- Clean 404s on missing records; CORS pinned to localhost:3000.

**Dashboard (`web/`)** — Next.js 15 App Router + TS + Tailwind v4 + Framer Motion
- Design tokens in OKLCH CSS variables (near-black mission-control theme; green=PASS,
  red=BLOCK, amber=warn, indigo accent; mono for ids/numbers).
- Screens: Overview (stat cards, pass-rate-by-version sparkline, gate-run table),
  Traces (list + span-waterfall detail), Eval suite (case grid with first-failed/fixed-in
  chips + ground-truth source), Regression diff (side-by-side field diff with changed-field
  highlighting + judge rationales — hero #1), Gate (live SSE case stream with regression
  snap-red, verdict resolution, publish action, optional voice — hero #2).
- Persistent top-bar controls: candidate version switcher (localStorage-backed),
  Run gate, Send test alert (3 canned alerts incl. the hero scenario).
- Loading skeletons, designed empty states, and error states with retry on every view.

**Ops & CI**
- `Makefile` (setup/seed/dev/demo/doctor/test/demo-check), `scripts/demo.sh` +
  `scripts/demo.ps1` (reset → doctor → API+web → printed runbook),
  `.github/workflows/recoil.yml` (tests + demo-check + gate on PRs), `.env.example`
  (every variable documented, REQUIRED vs OPTIONAL), `.gitignore`.

**Verification at build time**
- `pytest`: 14/14 passing (8 pure gate-logic tests + 6 seeded end-to-end tests).
- `recoil demo-check`: PASSED (BLOCK on v_regressed with hero case listed, PASS on
  v_fixed, all verdicts cache-served).
- `recoil doctor`: READY (warns only on optional layers: no API key, no voice, expected).
- `next build`: clean, type-checked, 7 routes.
- SSE stream verified end-to-end via curl: 12 case events → BLOCK verdict with 2
  regressed case ids; test-alert POST creates a judged run.

**Fixes during build**
- `seeding.py`: tuple/list bracket typo caught by pytest collection.
- `db.connect`: added `check_same_thread=False` after SSE thread error (see decision #1).
- `demo-check`: newly-fixed assertion originally compared v_fixed against v_good (both
  12/12 → zero newly-fixed, false failure); now asserts v_fixed vs v_regressed ≥ 2.
- Judge degradation warning made warn-once (was spamming once per seeded judgment).
