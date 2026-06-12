# RECOIL — Principal Architect Build Brief

**You are a Principal Software Architect and Staff Engineer.** You are going to build a complete, production-grade product called **Recoil** in a single working session. It will be demoed live, on stage, in ~6 hours, in front of senior infrastructure, data, and AI engineers at an AWS Builders Loft hackathon. The demo cannot fail. Your output must be correct, robust, beautifully designed, and reliable under live conditions. Optimize every decision for **"works flawlessly in a live demo"** over cleverness.

You have full autonomy. Do not ask the human questions. Make sound senior-engineer decisions and document them. Work in the phases below, and **do not advance to the next phase until the current phase's acceptance criteria pass.**

---

## 1. What Recoil is

**Recoil is CI/CD for AI agents — a regression-eval harness and publish gate.**

The thesis: everyone is shipping AI agents now (coding agents, support agents, ops agents), but there is no safety net that *learns from where an agent goes wrong and prevents it from regressing.* Today an agent works on Tuesday and silently breaks on Wednesday because someone tweaked a prompt, swapped a model, or upstream data shifted — and nobody catches it until a customer does.

Recoil closes that loop:

1. **Capture** every agent run as a structured (OpenTelemetry-style) trace.
2. **Judge** each run with an LLM-as-judge against a rubric and, where available, real ground truth.
3. **Freeze** every failure into a permanent, versioned regression eval case (the suite *grows itself*).
4. **Gate** the next deploy: re-run the whole suite on the new agent version and **block the publish if any previously-fixed case regresses** — exit non-zero, like a failing CI check.
5. **Announce** the verdict (optional spoken verdict via ElevenLabs for demo impact).

The one-sentence demo payoff the audience must *feel*: **"I made my agent 'more concise,' tried to ship, and Recoil physically stopped me because that change silently re-broke an incident-escalation case I fixed last week."**

---

## 2. Non-negotiable engineering principles

- **The core must run with zero external services.** With only an Anthropic API key (or even in pure mock mode), the entire demo loop must work end-to-end. Everything else is optional enrichment.
- **Verify before you integrate.** For ANY third-party SDK/API (AWS Bedrock, Airbyte, Guild.ai, ElevenLabs), fetch and read the *current* official docs before writing code against them. Never hardcode a CLI command, model ID, or endpoint you have not verified. If you cannot verify an external API quickly, implement the clean adapter interface and ship the local/mock implementation; mark the real integration as a toggleable path. Do not let any optional service block the build.
- **Demo determinism without faking.** Implement a `RECOIL_DEMO_MODE` that serves *real, previously-computed* judge results from cache on the demo's critical path so the live run never depends on network/model variance. This is caching genuine prior judgments — not fabricating outcomes. Outside demo mode, judging is live.
- **Every external call** is wrapped with timeouts, bounded retries with backoff, and a graceful fallback to cached/mock. No unhandled exception may ever reach the demo path.
- **The gate's correctness is the soul of the product.** Its regression logic must be unit-tested with explicit cases. If the gate is wrong, the product is worthless.
- **Production-quality only.** No placeholder UIs, no `TODO`-littered handlers, no console-log debugging left in, no dead code. Typed throughout. Sensible logging. Real loading/empty/error states everywhere.
- **Make setup trivial.** One `.env.example` with every variable documented and grouped REQUIRED vs OPTIONAL. A `make setup` that does everything. A `recoil doctor` command that prints a green/red readiness checklist so the human can confirm "all green" before going on stage.

---

## 3. Target architecture

A single monorepo. Suggested layout (adapt names sensibly, keep it this clean):

```
recoil/
  recoil/            # Python package: the engine + CLI (the product)
    tracing/         # trace + span capture -> SQLite (OpenTelemetry-style schema)
    judge/           # provider-agnostic LLM-as-judge (anthropic | bedrock | openai)
    evals/           # eval-case store, failure->case promotion, suite runner, caching
    gate/            # regression detection + verdict + exit codes (THE core)
    agent/           # the demo "agent under test", versioned
    adapters/        # ground_truth (mock default | airbyte), target (local default | guild)
    voice/           # ElevenLabs verdict (optional) + pre-rendered fallback
    cli.py           # `recoil` CLI (use Typer)
    doctor.py        # readiness checks
  server/            # FastAPI: serves traces/evals/gate state to dashboard + SSE stream
  web/               # Next.js + TypeScript + Tailwind + shadcn/ui dashboard
  scripts/
    seed.py          # seeds realistic production runs + a frozen eval suite
    demo.sh          # one-command live demo orchestration
  data/              # recoil.db (sqlite), frozen_evals/, audio/ (prerendered verdicts)
  .env.example
  Makefile           # setup / seed / dev / demo / doctor / test
  README.md
```

**Stack:** Python 3.11+ (managed with `uv`), FastAPI, SQLite (via SQLAlchemy or sqlite3 + a thin DAL — keep it simple and reliable), Typer for the CLI, Pydantic for all data contracts. Frontend: Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + a restrained amount of Framer Motion. Package the frontend with `pnpm`.

---

## 4. Data model (SQLite)

Implement these tables with proper types, indexes, and Pydantic models mirroring them. Use ISO timestamps and UUID string ids.

- **`agent_versions`** — `id`, `label` (e.g. "v3", "v4-concise"), `system_prompt`, `model`, `params_json`, `parent_version_id`, `is_published` (bool), `created_at`.
- **`runs`** (traces) — `id`, `agent_version_id`, `input_json`, `output_json`, `spans_json` (ordered list of spans: each span has `name`, `type` [llm|tool|retrieval], `start_ms`, `end_ms`, `model`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `attributes`), `ground_truth_ref`, `latency_ms`, `total_cost_usd`, `created_at`.
- **`eval_cases`** (frozen regression cases) — `id`, `source_run_id`, `title` (human-readable, e.g. "After-hours DB outage must escalate P1"), `input_json`, `context_snapshot_json` (ground truth + relevant state at capture time), `rubric` (text the judge grades against), `reference_behavior` (judge-articulated "what correct looks like"), `severity` (low|medium|high|critical), `status` (active|muted), `first_failed_version_id`, `fixed_in_version_id`, `created_at`.
- **`eval_results`** — `id`, `eval_case_id`, `agent_version_id`, `passed` (bool), `score` (0–1), `judge_rationale`, `actual_output_json`, `output_hash`, `from_cache` (bool), `created_at`. Unique on (`eval_case_id`, `agent_version_id`, `output_hash`).
- **`gate_runs`** — `id`, `candidate_version_id`, `baseline_version_id`, `total_cases`, `passed_count`, `failed_count`, `regressed_case_ids_json`, `newly_fixed_case_ids_json`, `verdict` (PASS|BLOCK), `created_at`.

---

## 5. The judge (provider-agnostic)

Define a single interface, e.g. `Judge.evaluate(input, output, rubric, reference_behavior, ground_truth) -> JudgeVerdict{passed: bool, score: float, rationale: str, reference_output: str}`.

- Providers selected by `RECOIL_JUDGE_PROVIDER` ∈ `anthropic | bedrock | openai`. Default `anthropic`.
- Use the model id from `RECOIL_JUDGE_MODEL`. For Anthropic direct, default to a current strong Claude model (look up the current model string from Anthropic docs; do not hardcode a stale one). For Bedrock, look up the correct current Claude model ID and region handling from AWS Bedrock docs at build time.
- Call with **temperature 0** and **structured JSON output** (tool-use / JSON mode), validated against a Pydantic schema. Retry on malformed output (bounded). Never crash on a bad model response — fall back to a conservative `passed=false` with a rationale noting the judge error, and log loudly.
- **Cache** every verdict keyed by (`eval_case_id`, `agent_version_id`, `output_hash`). In `RECOIL_DEMO_MODE`, the gate reads from cache first and only calls the model on a cache miss. Pre-warm the cache during seeding so the scripted demo path is fully cached.

The judge must be grounded, not vibes-based: where a `ground_truth` / `context_snapshot` exists, the rubric instructs the judge to grade the agent's output *against that ground truth*, not against its own priors. This is the technical credibility point for this audience — surface the ground-truth source in the UI.

---

## 6. The demo agent under test

Build a small but real **incident / support triage agent**. Input: an incoming alert or support message. Output (structured): `{ queue: str, priority: "P1".."P4", escalate: bool, on_call_paged: bool, reason: str }`. It calls the LLM with its versioned system prompt.

Seed **three stored versions** to drive the demo (this is a deliberate demo-safety decision — the presenter must never type a prompt live on stage):

- **`v_good`** (the published baseline) — correctly escalates after-hours, customer-impacting outages to P1 and pages on-call.
- **`v_regressed`** — a plausible "improvement" edit: the system prompt is changed to *"be concise and reduce escalation noise; only escalate clear emergencies during business hours."* This silently breaks the after-hours-outage class. **This is the candidate that gets BLOCKed.**
- **`v_fixed`** — the corrected version that keeps the concision improvement but preserves after-hours escalation. **This is the candidate that PASSes.** The on-stage "fix" is selecting this pre-seeded version, not editing text live.

All three versions' verdicts against the full suite must be pre-computed and cached during seeding, so the scripted demo path (BLOCK on `v_regressed`, PASS on `v_fixed`) runs entirely from cache with zero model variance. Live prompt-editing may be offered as a *secondary* "this is how it really works" path, but the primary demo path is the cached version switch.

The frozen eval suite (see §7) must contain ~12 realistic cases, one of which is the **"after-hours DB outage must escalate P1"** case that `v_good` passes, `v_regressed` fails, and `v_fixed` passes again. That single regression is the on-stage gut-punch.

---

## 7. Eval promotion + suite + seeding

- **Promotion:** when a run is judged FAIL, auto-promote it to a frozen `eval_case`, snapshotting input + ground truth/context + the judge's articulated `reference_behavior`, and recording `first_failed_version_id`. When a later version passes that case, set `fixed_in_version_id`. This is the "self-improving memory" — make it visible in the UI.
- **Seed (`scripts/seed.py`):** populate a believable production history that will withstand scrutiny from senior engineers — do not hand-wave the data.
  - **~250 production runs** spread across `v_good` and its parent versions over a simulated 2–3 week window, with realistic, *varied* latencies (judge/agent calls roughly 600–2400 ms, not uniform), token counts, and per-run cost in fractions of a cent. Spans must look like real APM traces (an LLM span plus 1–2 tool spans where appropriate).
  - **Exactly 12 frozen eval cases**, each promoted from a real seeded failure, spanning these archetypes so the suite reads as battle-earned, not invented: (1) the hero — after-hours DB outage must escalate P1; (2) PII leak — agent must redact a customer SSN/card number in its reason field; (3) billing dispute routed to the billing queue, not engineering; (4) non-English ticket correctly language-detected and routed; (5) low-severity "how do I reset my password" must NOT page on-call; (6) ambiguous "site feels slow" correctly triaged P3 with investigation, not dismissed; (7) duplicate/spam ticket suppressed; (8) security report (suspected breach) escalated to the security queue specifically; (9) angry-customer churn-risk flagged for human review; (10) feature request routed to product, not support; (11) partial-outage affecting one region escalated appropriately; (12) a known false-positive alert correctly de-prioritized. Mix the severities and make 2–3 of them `critical`.
  - Each case carries a concrete `context_snapshot` (the ground-truth the judge grades against) and a one-line human-readable `title`.
  - The dashboard must look like a live system on first load, never empty. Pre-compute and cache judge verdicts for all three demo versions against all 12 cases.

---

## 8. The gate (THE core — test it hard)

CLI: `recoil gate --candidate <version_label> --baseline <version_label>` (baseline defaults to the last published version).

Algorithm:
1. Resolve candidate + baseline versions.
2. Run candidate against every `active` eval case (use cache in demo mode; stream progress — see §9).
3. For each case classify: `regression` = baseline passed AND candidate failed; `newly_fixed` = baseline failed AND candidate passed; plus unchanged pass/fail.
4. Verdict = **BLOCK** if any regression exists, else **PASS**.
5. Persist a `gate_runs` row. Print a crisp, monospace result table (case, severity, baseline→candidate, ▲/▼). On BLOCK, print the offending cases prominently and exit code **1**. On PASS, exit **0**.

Also implement:
- `recoil publish --candidate <version>` — runs the gate, and only flips `is_published` if verdict is PASS; otherwise refuses and exits 1. **This is the CI/CD moment.**
- `recoil install-hook` — installs a git `pre-push` hook that runs `recoil gate`, so the "blocks your deploy" claim is literally true, not metaphor.
- Ship a sample **GitHub Actions workflow** (`.github/workflows/recoil.yml`) that runs the gate on PRs. Engineers in this room respect that the claim is real CI, not a toy.

**Unit tests (required):** regression detection (baseline-pass + candidate-fail → BLOCK), no-regression → PASS, newly-fixed counted but not blocking, empty-suite edge case, all-pass, all-fail. The gate must be provably correct.

---

## 9. API server + live streaming

FastAPI app exposing read APIs for the dashboard (overview stats, runs list + single trace, eval cases, single case with version history + diff, gate-run history) and an **SSE endpoint that streams a gate run case-by-case in real time.** The dashboard's live gate panel subscribes to this so the audience watches cases tick green one by one and then **snap red** on the regression. That visceral live moment is the demo's peak — make the streaming smooth and the timing legible (small, believable per-case delays are fine).

CORS configured for the local web origin. Pydantic response models throughout. Defensive: never 500 on a missing record — return clean 404s.

---

## 10. The dashboard (must be genuinely beautiful — no sloppy UI)

This is what the judges *see*. It must look like a serious, modern control-plane / observability product, not a hackathon throwaway.

**Design system (implement as CSS variables / Tailwind theme, used consistently):**
- **Aesthetic:** "mission control." Dense, precise, trustworthy. Reference points: Linear's restraint, Vercel's polish, an APM tool like Honeycomb/Datadog for the trace views — but cleaner.
- **Color:** near-black background (around `#0A0A0B`), layered elevated surfaces, AA-contrast text. One restrained brand accent (a confident indigo/violet). Reserve **green** for PASS and a sharp **red** for BLOCK as semantic verdict colors, amber for warnings. Define the palette in OKLCH via CSS variables; never inline hex in components.
- **Type:** a clean UI sans (Inter or Geist Sans) for chrome; a mono (JetBrains Mono / Geist Mono) for IDs, traces, code, diffs, costs. Establish a type scale; do not freestyle font sizes.
- **Spacing/radius:** a single 4px-based spacing scale and one consistent border-radius. No mismatched radii or random margins.
- **Components:** shadcn/ui throughout for consistency. Tables with monospace ids and right-aligned numerics. Motion via Framer Motion, subtle and purposeful only (gate cases ticking in; a controlled flash on regression). No gratuitous animation.
- **States:** every view has a skeleton loading state, a designed empty state, and an error state. No raw spinners on white.
- **A11y:** semantic HTML, keyboard navigable, AA contrast. No emoji in UI chrome.

**Screens:**
1. **Overview** — stat cards (production runs, eval cases, current suite pass-rate, last gate verdict), a pass-rate-over-time sparkline, recent gate runs.
2. **Traces** — runs list with latency/cost/version; click into a single run showing a **span waterfall** (llm/tool spans with durations, tokens, cost). This is candy for the infra judges — make it crisp.
3. **Eval suite** — grid of frozen cases with severity, status, "first failed in / fixed in" version chips, and the ground-truth source. Convey that the suite *grew itself from failures.*
4. **Regression diff (hero screen #1)** — for a regressed case, a side-by-side of baseline output vs candidate output with the differences highlighted and the judge's rationale shown. This is the "oh, damn" screen.
5. **Gate / Publish (hero screen #2)** — trigger a gate run; watch cases stream and resolve live via SSE; on BLOCK, the screen resolves to a clear, unmissable blocked verdict with the offending case(s) and (if enabled) the spoken verdict fires. On PASS, a clean green ship state.

Treat screens 4 and 5 as the two screens that win the room — give them disproportionate design care.

**Interactive controls (the dashboard must be DRIVABLE, not read-only — this is how the presenter performs the demo):**
- A persistent **agent version switcher** (dropdown showing `v_good (published)`, `v_regressed`, `v_fixed`) — selecting a candidate sets it as the gate target.
- A **"Run Gate" / "Attempt Publish"** primary action button that triggers the gate against the selected candidate and opens the live streaming view (screen 5).
- A **"Send test alert"** control on the Traces or Overview screen with 2–3 canned sample alerts (including the after-hours outage) that fires a real agent run, creates a real trace, and shows it appear — so the presenter can demonstrate a live run feeding the system.
- Every control must be keyboard-operable and have a clear disabled/loading state so a mis-click can't break the flow on stage.

**Diff computation (screen 4):** the agent output is structured JSON, so diff it **field by field** (queue, priority, escalate, on_call_paged, reason), highlighting changed fields semantically — not as a raw text diff. The `escalate: true → false` flip on the hero case must be visually unmissable.

---

## 11. Voice verdict (optional layer — graceful)

If `ELEVENLABS_API_KEY` is set, generate a short spoken verdict when the gate resolves: on BLOCK, something like *"Hold on — this update regressed the after-hours escalation case you fixed last week. Don't ship."*; on PASS, *"Cleared. Suite is green. Shipping."* Verify the current ElevenLabs API from their docs before coding. **Pre-render both verdicts to MP3 during seeding** and play the cached file if live generation is slow or the key is absent. The demo must never wait on this.

---

## 12. Optional sponsor adapters (verify-then-integrate, never load-bearing)

Implement each behind a clean interface with a working default, and only wire the real integration if you can verify its current API quickly:

- **AWS Bedrock judge** — a `Judge` provider (§5). Nice AWS-venue alignment. Verify the current Bedrock Claude model id + invoke API; fall back to the Anthropic-direct provider if access isn't ready.
- **Airbyte (ground-truth provider)** — the ground-truth adapter's real implementation pulls "what the human actually did" (e.g. from a ticketing system) to ground the judge. Default implementation is a local JSON ground-truth store. If you can verify the current Airbyte agent/connector SDK, wire one real connector; otherwise keep the local store and expose the interface so the integration story is true and demonstrable.
- **Guild.ai (publish target)** — Recoil is framework-agnostic; the default target is Recoil's own version store + `recoil publish`. If Guild.ai's current SDK/CLI is verifiable, add a Guild target adapter so `recoil` can gate a Guild agent's publish step. If not verifiable, keep the generic target and clearly support "any agent" — do not hardcode unverified Guild commands.

Document in the README exactly which integrations are live vs. interface-ready.

---

## 13. Setup, doctor, env

**`.env.example`** — every variable documented inline, grouped:
- REQUIRED: `RECOIL_JUDGE_PROVIDER` (default `anthropic`), `ANTHROPIC_API_KEY`, `RECOIL_JUDGE_MODEL`.
- OPTIONAL: AWS creds + region + `RECOIL_BEDROCK_MODEL_ID`; `ELEVENLABS_API_KEY` + voice id; Airbyte creds; Guild creds; `RECOIL_DEMO_MODE` (default `true`).

**`recoil doctor`** — checks Python/Node versions, dependencies installed, DB migrated, seed present, each configured provider reachable (with a fast timeout), and prints a green/red checklist ending in a single bold **READY / NOT READY**. The human will run this immediately before going on stage; it must be trustworthy.

**`Makefile`** targets: `setup` (install uv+pnpm deps, migrate, seed, pre-render audio), `seed`, `dev` (run API + web together), `demo` (run `scripts/demo.sh`), `doctor`, `test`.

---

## 13a. Operations, orchestration & rehearsal (demo-day plumbing — do not skip)

The product must be repeatedly rehearsable and trivially runnable. Build all of this:

**CLI completeness.** Beyond `gate` / `publish`, implement:
- `recoil run --version <label> --input <file-or-inline>` — invokes the agent, captures the trace, judges it, and (if it fails) promotes it to an eval case. This is how runs get created outside the UI and how you prove the capture→judge→freeze loop live.
- `recoil reset --demo` — restores the database to the pristine seeded demo state (published `v_good`, 12 cases, cached verdicts). The presenter runs this between every rehearsal and once right before going on stage, so a botched practice run never contaminates the real one. This must be fast (<2s) and idempotent.
- `recoil demo-check` — a headless end-to-end assertion: reset → gate `v_regressed` (assert verdict BLOCK, exit 1, the hero case is in the regression list) → gate `v_fixed` (assert verdict PASS, exit 0). Exits non-zero with a clear message if any assertion fails. This is the single command that proves the demo works without opening a browser; the human runs it during rehearsal and right before the talk.

**Ports & process orchestration.** Pin fixed ports (API e.g. `8787`, web e.g. `3000`) — never auto-random, so the presenter's muscle memory and any pre-opened tabs stay valid. `make dev` starts API and web together with clean, prefixed, readable logs and a single Ctrl-C that tears both down. Handle "port already in use" gracefully with a clear message, not a stack trace.

**`scripts/demo.sh`.** One command that: runs `recoil reset --demo`, confirms `recoil doctor` is green, starts API + web, and prints the exact ordered click/keystroke runbook for the §15 flow to the terminal so the presenter has it in front of them.

**Network-loss survival.** In `RECOIL_DEMO_MODE` (default on), the entire §15 path must complete with the laptop in airplane mode — every judge verdict served from cache, the voice verdict served from the pre-rendered MP3. Explicitly test this: the demo must pass `demo-check` with networking disabled.

---

## 14. Build order (strict — vertical slice first)

**Phase 0 — Scaffold.** Repo layout, tooling (`uv`, `pnpm`), env, Makefile, design tokens/theme, empty `recoil doctor`. *Gate: `make setup` runs clean; `recoil --help` works.*

**Phase 1 — Walking skeleton (your safety net).** Generic agent runs once → trace to SQLite → judge (cached/mock acceptable here) → one frozen eval case → `recoil gate` correctly BLOCKs a regression and exits 1, PASSes and exits 0, printing a readable verdict. End-to-end via CLI, ugly but fully working. *Gate: the regression scenario blocks and the fix passes, purely from the terminal.* **Do not proceed until this works — if you run out of time later, this alone is a demoable product.**

**Phase 2 — Real engine.** Provider-agnostic judge with grounding + caching; failure->case promotion; the three demo versions (§6) and full 12-case seed (§7); `recoil run`, `recoil reset --demo`, `recoil demo-check`; gate unit tests all green. *Gate: `make test` passes; `recoil demo-check` passes with networking disabled; seeded suite renders a believable history.*

**Phase 3 — API + SSE.** FastAPI read APIs + the streaming gate endpoint + the run-trigger and version-switch endpoints the dashboard controls need. *Gate: a gate run streams case-by-case over SSE; "send test alert" creates a real run.*

**Phase 4 — Dashboard.** All five screens to the design bar in §10, with the interactive controls (version switcher, Run Gate, Send test alert) and real loading/empty/error states. *Gate: the presenter can drive the entire §15 flow in the browser with no terminal; hero screens 4 & 5 look genuinely polished.*

**Phase 5 — CI/CD truth + polish.** `recoil publish`, `recoil install-hook`, the sample GitHub Action, full `recoil doctor`, `scripts/demo.sh`. *Gate: `recoil doctor` shows all green; `demo.sh` runs the scripted flow start to finish.*

**Phase 6 — Voice (optional).** ElevenLabs verdict + pre-rendered fallback.

**Phase 7 — Sponsor adapters (optional).** Bedrock judge, Airbyte ground truth, Guild target — each verify-then-integrate-else-interface-only.

**Phase 8 — Finalize.** README (what it is, architecture diagram in ASCII or mermaid, setup, the demo runbook, which integrations are live), and a final pass against the Definition of Done.

---

## 15. The demo the product must make possible

Build so this exact flow is rock-solid (the human will rehearse it):

1. Open dashboard → a real-looking production system: 200+ runs, a self-grown eval suite, last gate green.
2. Show a trace's span waterfall (tokens, latency, cost) — establish "this is real observability."
3. "I want my agent to be more concise." Switch the agent to `v_regressed` and run `recoil publish` (or trigger the gate from the UI).
4. Cases stream live… then one snaps **red**. Verdict: **BLOCK.** Exit code 1. (Optional voice fires.) Publish refused.
5. Open the regression-diff screen: baseline escalated the after-hours outage P1; the "improved" version dropped it. The judge explains why, grounded in the captured context.
6. Fix the prompt to preserve escalation. Re-run. Suite goes green. Verdict **PASS**, publish succeeds, suite is now N+1 cases.
7. Close: "Recoil is CI for agents. Every failure becomes a permanent test. Nothing regresses twice. It's the safety net every agent team is currently faking with a Notion doc."

---

## 16. Definition of Done (final acceptance checklist)

- [ ] With only `ANTHROPIC_API_KEY` set, `make setup` then `make demo` runs the full flow end-to-end with no errors.
- [ ] `recoil gate` BLOCKs the regression (exit 1) and PASSes the fix (exit 0); behavior matches the dashboard.
- [ ] Gate regression logic is covered by passing unit tests.
- [ ] All five dashboard screens meet the §10 design bar with real loading/empty/error states; no console errors.
- [ ] SSE gate streaming is smooth and legible.
- [ ] `recoil doctor` prints an accurate green/red checklist ending in READY.
- [ ] In `RECOIL_DEMO_MODE`, the scripted demo path runs entirely from cache and never depends on live network.
- [ ] Every external call has timeout + retry + graceful fallback; no unhandled exception can reach the demo path.
- [ ] Optional layers (voice, Bedrock, Airbyte, Guild) either work or degrade silently; README states which are live.
- [ ] README contains the architecture, setup, and the exact demo runbook.
- [ ] No dead code, no stray debug logging, typed throughout.

---

## 17. How to work (you, the coding agent)

- Build the **walking skeleton first**; keep a working end-to-end demo at every checkpoint so quality only ever increases.
- Verify external APIs against current docs before coding against them; never hardcode unverified commands, model ids, or endpoints.
- Prefer boring, reliable choices over clever ones on the demo path.
- Test the gate logic; it is the product.
- Make the two hero screens beautiful.
- Leave the human a one-command demo and a trustworthy `recoil doctor`.

Begin with Phase 0 now. Report what you built and the acceptance result at the end of each phase before moving on.
