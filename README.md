# Recoil — CI/CD for AI agents

**A regression-eval harness and publish gate.** Recoil captures every agent run as a structured trace, judges it against ground truth with an LLM-as-judge, freezes every failure into a permanent regression case, and **blocks the next deploy if any previously-fixed case regresses** — exit code 1, like a failing CI check.

> Every failure becomes a permanent test. Nothing regresses twice.

## Architecture

```
            ┌──────────────────────────────────────────────────────────┐
            │                        recoil (Python)                   │
            │                                                          │
  alert ───►│  agent/ ──run──► tracing/ ──trace──► SQLite (data/)      │
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
                      │ cli.py (Typer)                    │ server/ (FastAPI)
                      ▼                                   ▼  SSE: /api/gate/stream
              recoil gate|publish|run|              web/ (Next.js dashboard)
              reset|demo-check|doctor               Overview · Traces · Eval suite
                                                    Regression diff · Live gate
```

**Stack:** Python 3.11+ · FastAPI · SQLite (stdlib, thin DAL) · Typer · Pydantic v2 · Next.js (App Router) + TypeScript + Tailwind v4 + Framer Motion.

## Setup

```bash
# POSIX
make setup          # venv + pip install + npm install + seed + doctor

# Windows (no make)
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
cd web && npm install && cd ..
.venv\Scripts\recoil reset --demo
.venv\Scripts\recoil doctor
```

Copy `.env.example` to `.env` if you want live judging (`ANTHROPIC_API_KEY`) or voice (`ELEVENLABS_API_KEY`). **Nothing is required**: with no env at all, Recoil runs fully offline on the deterministic grounded mock judge and cached verdicts.

> Note: the original brief suggested `uv` + `pnpm`; this build uses stdlib `venv` + `npm` because those are what the demo machine has. Swap freely — nothing depends on the package manager.

## Run it

```bash
make dev            # API :8787 + web :3000 together (Ctrl-C stops both)
make demo           # reset -> doctor -> start both -> print the runbook
# Windows: powershell -File scripts\demo.ps1
```

CLI surface:

| Command | What it does |
|---|---|
| `recoil gate --candidate v_regressed` | Run the regression suite vs the published baseline. **Exit 1 on BLOCK, 0 on PASS.** |
| `recoil publish --candidate v_fixed` | Gate first; only flips `is_published` on PASS. |
| `recoil run --version v_good --input alert.json` | Run agent → capture trace → judge → freeze on FAIL. |
| `recoil reset --demo` | Restore pristine seeded demo state (<2s, idempotent). |
| `recoil demo-check` | Headless assertion: BLOCK on `v_regressed`, PASS on `v_fixed`. Run before going on stage. |
| `recoil doctor` | Green/red readiness checklist ending in READY / NOT READY. |
| `recoil install-hook` | Git `pre-push` hook that runs the gate — the deploy block is literal. |
| `recoil serve` | Start the API on the pinned port 8787. |

There is also a sample GitHub Actions workflow at `.github/workflows/recoil.yml` that runs tests, `demo-check`, and the gate on every PR.

## The demo (rehearsed flow)

1. **Overview** — 250 production runs, a 12-case suite grown from real failures, last gate green, `v_good` published.
2. **Traces** — open any run, show the span waterfall (LLM + tool spans, tokens, latency, cost).
3. *"Let's make the agent more concise."* Top bar → candidate `v_regressed` → **Run gate**. Cases stream and tick green… then **"After-hours DB outage must escalate P1" snaps red**. Verdict: **BLOCK**, publish refused, exit 1.
4. **Regression diff** — `escalate: true → false`, `on_call_paged: true → false`, highlighted field-by-field, with the judge's rationale grounded in the captured context snapshot.
5. Candidate `v_fixed` (keeps concision, restores after-hours escalation) → **Run gate** → 12/12 → **PASS** → **Publish**.
6. Optional: **Send test alert** fires a real agent run live; a failing run is frozen into a new case on the spot (suite grows to N+1).

Demo determinism: in `RECOIL_DEMO_MODE` (default on) every verdict on this path is a real, previously-computed judgment served from cache — the flow completes in airplane mode. `recoil demo-check` proves it headlessly.

## Data model

SQLite at `data/recoil.db`: `agent_versions` (versioned prompts, `is_published`), `runs` (OTel-style spans JSON, latency, cost), `eval_cases` (frozen input + ground-truth context snapshot + rubric + `first_failed_version_id`/`fixed_in_version_id`), `eval_results` (verdict cache, unique on case+version+output hash), `gate_runs` (verdict history). Pydantic models mirror every table (`recoil/models.py`).

## Judge

One interface (`Judge.evaluate(...) -> JudgeVerdict`), four providers selected by `RECOIL_JUDGE_PROVIDER`:

- **anthropic** (default) — structured JSON output, bounded retries, conservative `passed=false` on judge error. Default model `claude-opus-4-8` (the `temperature` parameter is omitted on models that reject it).
- **bedrock** — same request shape via `AnthropicBedrock`; model ids carry the `anthropic.` prefix.
- **openai** — JSON-mode chat completions.
- **mock** — deterministic, grounded field-by-field grading against the captured ground truth. This is what seeds the verdict cache and what everything degrades to when unconfigured.

The judge is grounded, not vibes-based: where a context snapshot exists, it grades against that ground truth, and the dashboard surfaces the ground-truth source on every case.

## Integration status

| Integration | Status |
|---|---|
| Anthropic direct judge | **Live** (with `ANTHROPIC_API_KEY`) |
| Deterministic mock judge + verdict cache | **Live** (default, offline) |
| AWS Bedrock judge | **Live code path**, needs AWS credentials; degrades to Anthropic/mock |
| OpenAI judge | **Live code path**, needs `OPENAI_API_KEY`; degrades to mock |
| ElevenLabs spoken verdict | **Live code path**, pre-rendered at seed time; silent no-op without key |
| Airbyte ground truth | **Interface-ready** (`GroundTruthProvider`); local JSON store is the working default |
| Guild.ai publish target | **Interface-ready** (`PublishTarget`); Recoil's version store is the working default |

## Tests

```bash
make test   # or: .venv/Scripts/python -m pytest -q
```

14 tests cover the gate's regression logic exhaustively (regression→BLOCK, newly-fixed not blocking, empty suite, all-pass/all-fail, new-case handling) plus the end-to-end seeded demo path and cache behavior.
