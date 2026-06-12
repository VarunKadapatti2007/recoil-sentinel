# Recoil Sentinel — Hackathon Implementation Plan (LOCKED)

> **Pivot (2026-06-12):** The "Context Engineering Challenge — agents that act on the
> open web" does NOT fit Recoil-as-a-CI-gate. We invert it: build a **real autonomous
> crypto on-chain intelligence agent** that publishes cited reports to `cited.md`,
> charges for them via **x402**, and is **gated by Recoil's regression engine** so it
> can never republish a mistake it already learned from. The acting agent is the star;
> Recoil's gate/self-growing-memory is the trust differentiator ("Most Innovative Use
> of Agents"). Everything runs on **real, live data** — no mock on the demo path.

## Locked stack
- **Domain:** Crypto / on-chain intelligence (protocol TVL, price, governance, exploit/risk signals).
- **Payment rail:** x402 (HTTP 402, Coinbase) gating premium reports.
- **Sponsor tools (all load-bearing):** Airbyte Agent Engine (ground-truth ingestion),
  ClickHouse (trace/eval/event store + real-time analytics), Composio (real web actions:
  GitHub issue / Slack post).
- **Deploy:** Render (always-on web service + cron) → satisfies Autonomy.
- **Model:** Anthropic `claude-opus-4-8` (judge) / `claude-sonnet-4-6` (agent).

## Target architecture
```
            ┌──────────────── RECOIL SENTINEL (autonomous, on Render cron) ────────────────┐
            │                                                                               │
  live web ─┤ Airbyte Agent Engine ──► ground-truth knowledge (DefiLlama/CoinGecko/chain)  │
  sources   │            │                                                                  │
            │            ▼                                                                  │
            │   crypto intel agent (Anthropic) ── researches + writes CITED report         │
            │            │                              │                                   │
            │            │ trace (Langfuse-style)       ▼                                   │
            │            ▼                        RECOIL JUDGE (grounded vs Airbyte truth)  │
            │   ClickHouse (runs/evals/events)          │ FAIL → freeze regression case    │
            │            │                              ▼                                   │
            │            │                    RECOIL GATE: regressed? ── BLOCK publish      │
            │            │                              │ PASS                              │
            │            ▼                              ▼                                   │
            │   real-time dashboard          PUBLISH ──► cited.md  +  Composio action       │
            │                                           (GitHub issue / Slack)              │
            │                                              │                                │
            │                                   x402 paywall ($) on premium report endpoint │
            └───────────────────────────────────────────────────────────────────────────────┘
```

## Sponsor-tool → pipeline-stage map (Tool Use = 20%, keep each load-bearing)
| Tool | Stage | Acceptance proof |
|---|---|---|
| Airbyte Agent Engine | Pull ground-truth knowledge the agent cites + the judge grades against | A real connector sync populates the ground-truth store from a live source |
| ClickHouse | Store every run/eval/monitor event; power the real-time dashboard | Dashboard reads ClickHouse; rows grow as the agent runs |
| Composio | Agent takes a real web action on publish | A real GitHub issue or Slack message is created autonomously |
| x402 | Monetize the premium report | A 402 challenge → payment → unlocked report, observed live |
| Render | Always-on autonomous deploy | The loop runs on a schedule with zero manual trigger |

## Credentials checklist (THE blocker — gather these in parallel)
- [ ] `ANTHROPIC_API_KEY` — agent + judge (required, real path).
- [ ] Crypto data: **keyless to start** — DefiLlama (TVL/protocols) + CoinGecko public.
      Optional: Etherscan free key, a Base/Ethereum RPC (Alchemy free tier).
- [ ] **ClickHouse Cloud** free trial → host / user / password.
- [ ] **Composio** API key + one connected account (GitHub or Slack).
- [ ] **Airbyte** Cloud / Agent Engine access (or self-host) → API key/workspace.
- [ ] **x402**: an EVM (Base) wallet + CDP API key for the facilitator/settlement.
- [ ] **Render** account (deploy from the GitHub repo).
- [ ] Public **GitHub repo** (submission requirement) + the `cited.md` lives there.

## Phased build (each phase ships something real; verify every external API vs current docs first)

### Phase A — Real agent + cited.md spine  *(no sponsor creds except Anthropic)*
- Replace the deterministic behavior profiles with a **real Anthropic crypto-intel agent**
  that ingests a live source (keyless DefiLlama/CoinGecko) and emits a **structured,
  cited** report (claims each carry a source URL + retrieved value).
- Write the report to `cited.md` with inline citations and a machine-readable JSON sidecar.
- **Accept:** `recoil sentinel run` pulls live data, produces a cited report, writes cited.md;
  every claim has a resolvable citation. No mock.

### Phase B — Ground the judge on real truth  *(Airbyte)*
- Wire one real Airbyte connector pulling the ground-truth dataset the agent cites.
- Judge grades the report's claims against that synced truth (numeric tolerance, staleness,
  hallucinated-source detection).
- **Accept:** a deliberately wrong claim is caught and scored FAIL with a grounded rationale.

### Phase C — Real tracing + storage  *(ClickHouse)*
- Persist runs/evals/monitor-events to ClickHouse; dashboard reads from it.
- **Accept:** rows appear in ClickHouse per run; dashboard reflects live counts.

### Phase D — Real action  *(Composio)*
- On a publishable report, the agent autonomously opens a GitHub issue / posts to Slack via Composio.
- **Accept:** a real issue/message is created by the agent, link shown in the dashboard.

### Phase E — Monetize  *(x402)*
- Gate the premium report endpoint behind x402; verify the current x402 spec/facilitator.
- **Accept:** unpaid request → 402 challenge; paid → unlocked report. Observed live.

### Phase F — Recoil gate over REAL reports
- The existing gate/promotion runs over real judged reports: a regressed claim/behavior
  BLOCKs the publish (exit 1) before cited.md is written.
- **Accept:** introduce a regression in the agent prompt → gate BLOCKs → cited.md NOT updated.

### Phase G — Always-on deploy + 3-min demo  *(Render)*
- Deploy the loop on a Render cron/web service; it runs with no human.
- **Accept:** the scheduled run executes autonomously; the recorded demo shows the full
  real path end to end.

## 3-minute demo script (must show the REAL path)
1. (0:00) "Autonomous crypto-intel agent, live on Render." Show the schedule firing.
2. (0:30) Agent pulls live on-chain/TVL data (Airbyte ground truth), writes a cited report → cited.md.
3. (1:10) Composio: it autonomously opens a GitHub issue / Slack post with the finding.
4. (1:40) x402: a buyer agent pays to unlock the premium report (402 → paid → unlocked).
5. (2:10) The Recoil twist: change the model/prompt → the gate catches a regressed claim
   against ground truth → publish BLOCKED. "It can't repeat a mistake it already learned."
6. (2:40) ClickHouse dashboard: real-time runs/evals. Close on autonomy + trust.

## Judging-criteria coverage (each 20%)
- **Idea:** trustworthy autonomous publisher — novel gate/memory wedge. ✓
- **Technical:** real ingestion, grounding, tracing, gating, payments, deploy. ✓
- **Tool Use:** Airbyte + ClickHouse + Composio + x402 + Render, all load-bearing. ✓
- **Presentation:** the script above; the BLOCK moment is the memorable beat. ✓
- **Autonomy:** Render cron, no manual trigger, acts on live data. ✓

## Honest risks
- **x402 + Airbyte Agent Engine + Composio each need doc verification + real access**; any can
  block. Build the credential-free spine (A) first; treat payments (E) as the highest-risk item.
- Keep the project principle: real path + graceful fallback, but the **recorded demo must show
  the real path succeeding at least once** — mock data will not survive the Autonomy criterion.
- This is a multi-session build. Sequence A→G; never advance past a phase whose Accept fails.
```
