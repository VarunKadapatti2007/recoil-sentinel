# recoil sentinel

> an autonomous crypto-intel agent that pulls live data, writes a cited report with a real llm, and refuses to publish unless every number checks out against its source — and it remembers every mistake so it can't make the same one twice.

basically: an agent you can actually trust, because it grades itself against ground truth before it ever hits publish, and it has ci-style regression memory bolted on.

## the core idea

most agents can hallucinate the same wrong number over and over. this one can't.

every run does the same four steps:

1. **fetch ground truth first** — live snapshot from keyless apis (coingecko prices, defillama tvl, or the blockchain itself via json-rpc). every metric keeps its source url + timestamp. no data = agent doesn't run.
2. **generate** — real anthropic call (`claude-sonnet-4-6`) with structured output. the model may only cite metric keys that exist in the snapshot, and has to echo the exact numbers it used.
3. **verify** — deterministic code (not an llm) checks every claim: unknown metric key = hallucinated source = fail; number off by more than 1% = fail.
4. **gate + freeze** — `cited.md` is written only if everything verified. a failure gets frozen as a permanent test case, and future runs replay it — so a mistake it already learned from blocks the next publish (exit 1, like a failing ci check).

> every failure becomes a permanent test. nothing regresses twice.

## architecture

```
            ┌──────────────────────────────────────────────────────────┐
            │                        recoil (python)                   │
            │                                                          │
  alert ───►│  agent/ ──run──► tracing/ ──trace──► sqlite (data/)      │
            │                     │                    ▲               │
            │                     ▼                    │               │
            │  judge/ ◄── ground truth (adapters/) ────┤               │
            │  (anthropic|bedrock|openai|mock,         │               │
            │   verdicts cached by output hash)        │               │
            │                     │ FAIL                               │
            │                     ▼                                    │
            │  evals/  failure ──promote──► frozen eval case           │
            │                     │                                    │
            │                     ▼                                    │
            │  gate/   baseline vs candidate ──► PASS (exit 0)         │
            │          regression detected   ──► BLOCK (exit 1)        │
            │                     │                                    │
            │  voice/  spoken verdict (optional, pre-rendered)         │
            └─────────┬───────────────────────────────────┬────────────┘
                      │ cli.py (typer)                    │ server/ (fastapi)
                      ▼                                   ▼  sse: /api/gate/stream
              recoil gate|publish|run|              web/ (next.js dashboard)
              reset|demo-check|doctor               overview · traces · eval suite
                                                    regression diff · live gate
```

**stack:** python 3.11+ · fastapi · sqlite (stdlib, thin dal) · typer · pydantic v2 · next.js (app router) + typescript + tailwind v4 + framer motion.

## one engine, three domains

same `generate → verify → gate → freeze` loop, just swap the ground-truth source:

- **market intel** — coingecko + defillama (the main demo)
- **on-chain integrity** — the blockchain itself via keyless json-rpc (an agent that can't lie about money)
- **agent regression gate** — the original recoil: an incident-triage agent graded against operator ground truth

## setup

```bash
# posix
make setup          # venv + pip install + npm install + seed + doctor

# windows (no make)
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
cd web && npm install && cd ..
.venv\Scripts\recoil reset --demo
.venv\Scripts\recoil doctor
```

copy `.env.example` to `.env` if you want live judging (`ANTHROPIC_API_KEY`), voice (`ELEVENLABS_API_KEY`), or the sponsor integrations. **nothing is required** — with no env at all it runs fully offline on the deterministic mock judge + cached verdicts.

## run it

```bash
make dev            # api :8787 + web :3000 together (ctrl-c stops both)
make demo           # reset -> doctor -> start both -> print the runbook
# windows: powershell -File scripts\demo.ps1
```

## cli

| command | what it does |
|---|---|
| `recoil sentinel` | the real autonomous run: live data -> llm -> verify every claim -> publish cited.md on pass. `--tamper` plants a fake number so you can watch the gate catch it; `--focus "<topic>"` steers the analysis. |
| `recoil verify-wallet` | same engine, but ground truth is the chain. verifies a wallet's on-chain state; `--tamper` shows a block. |
| `recoil gate --candidate v_regressed` | run the regression suite vs the published baseline. **exit 1 on block, 0 on pass.** |
| `recoil publish --candidate v_fixed` | gate first; only flips `is_published` on pass. |
| `recoil run --version v_good --input alert.json` | run agent → capture trace → judge → freeze on fail. |
| `recoil reset --demo` | restore the pristine seeded demo state (<2s, idempotent). |
| `recoil demo-check` | headless check: block on `v_regressed`, pass on `v_fixed`. run before going on stage. |
| `recoil doctor` | green/red readiness checklist ending in READY / NOT READY. |
| `recoil install-hook` | git pre-push hook that runs the gate — makes the deploy block literal. |
| `recoil serve` | start the api on the pinned port 8787. |

there's also a github actions workflow at `.github/workflows/recoil.yml` that runs tests, `demo-check`, and the gate on every pr.

## the demo flow

1. **overview** — 250 production runs, a 12-case suite grown from real failures, last gate green, `v_good` published.
2. **traces** — open any run, show the span waterfall (llm + tool spans, tokens, latency, cost).
3. *"let's make the agent more concise."* top bar → candidate `v_regressed` → **run gate**. cases tick green… then **"after-hours db outage must escalate p1" snaps red**. verdict: **block**, publish refused, exit 1.
4. **regression diff** — `escalate: true → false`, `on_call_paged: true → false`, highlighted field by field, with the judge's rationale grounded in the captured snapshot.
5. candidate `v_fixed` (keeps concision, restores after-hours escalation) → **run gate** → 12/12 → **pass** → **publish**.
6. optional: **send test alert** fires a real run live; a failing run gets frozen into a new case on the spot.

demo determinism: in `RECOIL_DEMO_MODE` (default on) every verdict on this path is a real, previously-computed judgment served from cache — the flow works in airplane mode. `recoil demo-check` proves it headlessly. the sentinel path ignores this flag and always runs live.

## data model

sqlite at `data/recoil.db`:
- `agent_versions` — versioned prompts, `is_published`
- `runs` — otel-style spans json, latency, cost
- `eval_cases` — frozen input + ground-truth snapshot + rubric + `first_failed_version_id` / `fixed_in_version_id`
- `eval_results` — the verdict cache, unique on case + version + output hash
- `gate_runs` — verdict history

pydantic models mirror every table (`recoil/models.py`).

## the judge

one interface (`Judge.evaluate(...) -> JudgeVerdict`), four backends picked by `RECOIL_JUDGE_PROVIDER`:

- **anthropic** (default) — structured json, bounded retries, conservative `passed=false` on error. default model `claude-opus-4-8`.
- **bedrock** — same shape via `AnthropicBedrock`; model ids carry the `anthropic.` prefix.
- **openai** — json-mode chat completions.
- **mock** — deterministic, grounded field-by-field grading. seeds the verdict cache and is what everything degrades to when unconfigured.

it's grounded, not vibes-based: where a snapshot exists it grades against that ground truth, and the dashboard shows the source on every case.

## sponsor integrations

all in `recoil/sentinel/integrations.py`. each one only turns on when its creds exist, runs the real service, and degrades to a status string on failure — a sponsor outage never blocks the publish loop.

| integration | role | status |
|---|---|---|
| senso / cited.md | the publish destination — verified reports become live public articles | **live** |
| clickhouse cloud | mirrors every run for real-time analytics | **live** |
| composio | the agent opens a real github issue on publish | **live** |
| x402 (coinbase http-402) | paywalls the premium report ($0.01 usdc on base-sepolia) | **live** |
| airbyte | ground-truth ingestion control plane | **live code path** |
| render | always-on deploy + in-process scheduler (no cron, no human) | **live** |
| anthropic direct judge | grades reports/triage | **live** (with key) |
| elevenlabs spoken verdict | pre-rendered at seed time; silent no-op without key | **live code path** |

## tests

```bash
make test   # or: .venv/Scripts/python -m pytest -q
```

covers the gate's regression logic exhaustively (regression→block, newly-fixed not blocking, empty suite, all-pass/all-fail, new-case handling), the sentinel verify/freeze/replay path, plus the end-to-end seeded demo and cache behavior.
