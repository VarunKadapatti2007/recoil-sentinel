"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import {
  runMarketVerification,
  runWalletVerification,
  type VerificationRun,
} from "@/lib/api";
import { Badge, Button, Card, CardBody, Mono, VerdictPill } from "@/components/ui";

type Mode = "market" | "wallet";

const STEPS = [
  "Fetching ground truth from the live source",
  "Agent generating structured claims",
  "Verifying every claim against ground truth",
  "Rendering verdict",
];

function GroundTruthPanel({ run }: { run: VerificationRun }) {
  return (
    <Card>
      <CardBody>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">
          1 · Ground truth ({run.domain === "wallet" ? "live blockchain" : "live market data"})
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
          {run.ground_truth.slice(0, 10).map((g) => (
            <a
              key={g.key}
              href={g.source_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-baseline justify-between gap-3 border-b border-border/40 py-1 hover:bg-surface-2/40"
            >
              <span className="truncate text-[12px] text-text-2">{g.label}</span>
              <Mono className="shrink-0 text-text-1">
                {typeof g.value === "number" ? g.value.toLocaleString() : g.value}
              </Mono>
            </a>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function VerificationTable({ run }: { run: VerificationRun }) {
  const truthByKey = Object.fromEntries(run.ground_truth.map((g) => [g.key, g]));
  return (
    <Card>
      <CardBody className="px-0 pb-0">
        <div className="px-4 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">
          3 · Claim-by-claim verification against ground truth
        </div>
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr>
              <th className="border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
                claimed metric
              </th>
              <th className="border-b border-border px-4 py-2 text-right text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
                agent claimed
              </th>
              <th className="border-b border-border px-4 py-2 text-right text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
                ground truth
              </th>
              <th className="border-b border-border px-4 py-2 text-center text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
                check
              </th>
            </tr>
          </thead>
          <tbody>
            {run.verification.checks.map((c, i) => (
              <motion.tr
                key={`${c.metric_key}-${i}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.05 }}
                className={c.ok ? "" : "bg-block-soft/40"}
              >
                <td className="border-b border-border/50 px-4 py-2">
                  <Mono className={c.ok ? "text-text-2" : "font-semibold text-text-1"}>
                    {truthByKey[c.metric_key]?.label ?? c.metric_key}
                  </Mono>
                </td>
                <td className="border-b border-border/50 px-4 py-2 text-right">
                  <Mono className={c.ok ? "text-text-2" : "font-semibold text-block"}>
                    {c.claimed == null ? "—" : c.claimed.toLocaleString()}
                  </Mono>
                </td>
                <td className="border-b border-border/50 px-4 py-2 text-right">
                  <Mono className="text-text-2">
                    {c.observed == null ? "—" : c.observed.toLocaleString()}
                  </Mono>
                </td>
                <td className="border-b border-border/50 px-4 py-2 text-center">
                  {c.ok ? (
                    <span className="font-mono text-pass">✓ match</span>
                  ) : (
                    <span className="font-mono font-semibold text-block">✕ MISMATCH</span>
                  )}
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
        {run.problems.length > 0 ? (
          <div className="border-t border-border bg-block-soft/30 px-4 py-3">
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-block">
              why it was blocked
            </div>
            {run.problems.map((p, i) => (
              <div key={i} className="font-mono text-[12px] text-text-2">
                {p}
              </div>
            ))}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

export default function VerifyPage() {
  const [mode, setMode] = useState<Mode>("market");
  const [focus, setFocus] = useState("");
  const [tamper, setTamper] = useState(false);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(0);
  const [run, setRun] = useState<VerificationRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setRunning(true);
    setRun(null);
    setError(null);
    setStep(0);
    const ticker = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 7000);
    try {
      const result =
        mode === "market"
          ? await runMarketVerification(focus, tamper)
          : await runWalletVerification(tamper);
      setRun(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      clearInterval(ticker);
      setRunning(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div>
        <h1 className="text-[15px] font-semibold">Verification console</h1>
        <p className="mt-1 text-[12.5px] text-text-3">
          Give the agent an instruction. Watch it fetch ground truth, make claims, and have every
          claim machine-verified before anything is published — and watch it refuse when a claim
          doesn&apos;t hold up.
        </p>
      </div>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <div className="flex gap-2">
            <Button variant={mode === "market" ? "primary" : "secondary"} onClick={() => setMode("market")}>
              Market intel
            </Button>
            <Button variant={mode === "wallet" ? "primary" : "secondary"} onClick={() => setMode("wallet")}>
              Wallet / transaction integrity
            </Button>
          </div>

          {mode === "market" ? (
            <input
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              placeholder="e.g. analyze Solana DeFi protocols and stablecoin risk"
              className="h-10 rounded-md border border-border-strong bg-surface-2 px-3 text-[13px] text-text-1 focus-visible:outline-2 focus-visible:outline-accent"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !running) void submit();
              }}
            />
          ) : (
            <div className="rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-[12px] text-text-2">
              Verifies the configured wallet&apos;s real on-chain balances (ETH, USDC, nonce) against
              the live blockchain.
            </div>
          )}

          <label className="flex w-fit cursor-pointer items-center gap-2 text-[12.5px] text-text-2">
            <input
              type="checkbox"
              checked={tamper}
              onChange={(e) => setTamper(e.target.checked)}
              className="accent-[oklch(0.64_0.22_25)]"
            />
            Inject a false claim (demo the BLOCK)
          </label>

          <div className="flex items-center gap-3">
            <Button variant="primary" onClick={() => void submit()} disabled={running}>
              {running ? "Verifying…" : "Run verification"}
            </Button>
            <span className="text-[11.5px] text-text-3">
              Live model call · ~30s · grounded in {mode === "wallet" ? "the blockchain" : "live market data"}
            </span>
          </div>
        </CardBody>
      </Card>

      {running ? (
        <Card>
          <CardBody className="flex flex-col gap-2">
            {STEPS.map((s, i) => (
              <div key={s} className="flex items-center gap-2.5 text-[13px]">
                <span
                  className={`inline-block size-2 rounded-full ${
                    i < step ? "bg-pass" : i === step ? "animate-soft-pulse bg-accent" : "bg-surface-3"
                  }`}
                />
                <span className={i <= step ? "text-text-1" : "text-text-3"}>{s}</span>
              </div>
            ))}
          </CardBody>
        </Card>
      ) : null}

      {error ? (
        <Card className="border-block/40">
          <CardBody className="font-mono text-xs text-block">{error}</CardBody>
        </Card>
      ) : null}

      <AnimatePresence>
        {run ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col gap-4"
          >
            <Card className={run.verdict === "PASS" ? "border-pass/50" : "border-block/60"}>
              <CardBody className="flex items-center justify-between">
                <div>
                  <div className="text-[13px] font-medium text-text-1">{run.title}</div>
                  <div className="mt-0.5 text-[11.5px] text-text-3">{run.subject_label}</div>
                  {run.injected_fault ? (
                    <div className="mt-1.5">
                      <Badge tone="warn">fault injected: {run.injected_fault}</Badge>
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-col items-end gap-1.5">
                  <VerdictPill verdict={run.verdict} large />
                  <Mono className="text-[11px]">{run.claims_verified} claims verified</Mono>
                </div>
              </CardBody>
            </Card>

            <GroundTruthPanel run={run} />

            <Card>
              <CardBody>
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">
                  2 · Agent claims
                </div>
                <div className="flex flex-col gap-2">
                  {run.findings.map((f, i) => (
                    <div key={i} className="rounded-md border border-border bg-surface-2 px-3 py-2">
                      <div className="text-[13px] font-medium text-text-1">{f.headline}</div>
                      <div className="mt-0.5 text-[12px] text-text-2">{f.body}</div>
                    </div>
                  ))}
                </div>
              </CardBody>
            </Card>

            <VerificationTable run={run} />

            <Card className={run.verdict === "PASS" ? "border-pass/40" : "border-block/50"}>
              <CardBody className="text-[12.5px] text-text-2">
                {run.verdict === "PASS" ? (
                  <>
                    <span className="font-semibold text-pass">PASS</span> — every claim matched ground
                    truth, so the report was published
                    {run.report_url ? " to cited.md" : ""}. Integrations:{" "}
                    {run.integrations
                      ? Object.entries(run.integrations)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(" · ")
                      : "—"}
                  </>
                ) : (
                  <>
                    <span className="font-semibold text-block">BLOCK</span> — a claim did not match
                    ground truth, so publication was refused, nothing was acted on, and the failure
                    was frozen into the regression suite so it can never recur.
                  </>
                )}
              </CardBody>
            </Card>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
