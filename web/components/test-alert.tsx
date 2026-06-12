"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Badge, Button, Mono } from "@/components/ui";
import { useVersions } from "@/components/version-context";

interface CannedAlert {
  key: string;
  label: string;
  input: Record<string, unknown>;
}

const CANNED: CannedAlert[] = [
  {
    key: "after_hours_outage",
    label: "After-hours DB outage (the hero scenario)",
    input: {
      kind: "outage",
      scope: "full",
      title: "Primary Postgres cluster unreachable",
      message:
        "ALERT db-primary-01: connection refused on 5432; checkout failing for all tenants.",
      channel: "pagerduty-webhook",
      local_hour: 2,
      region: "us-east-1",
      customer_impact: true,
      _expected: { queue: "incident", priority: "P1", escalate: true, on_call_paged: true },
    },
  },
  {
    key: "password_reset",
    label: "Routine password reset (must not page)",
    input: {
      kind: "password_reset",
      title: "How do I reset my password?",
      message: "Forgot my password, the reset email never arrived.",
      channel: "chat",
      local_hour: 15,
      _expected: { queue: "support", priority: "P4", escalate: false, on_call_paged: false },
    },
  },
  {
    key: "security_report",
    label: "Suspected credential stuffing (security)",
    input: {
      kind: "security",
      title: "Possible credential stuffing on login endpoint",
      message: "40k failed logins from rotating IPs in 10 minutes.",
      channel: "siem-webhook",
      local_hour: 16,
      _expected: { queue: "security", priority: "P1", escalate: true, on_call_paged: true },
    },
  },
];

interface AlertResult {
  run_id: string;
  output: Record<string, unknown>;
  latency_ms: number;
  judge_passed: boolean;
  judge_rationale: string;
  promoted_case_id: string | null;
}

export function TestAlertDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { candidate } = useVersions();
  const router = useRouter();
  const [selected, setSelected] = useState(CANNED[0].key);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<AlertResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      setResult(null);
      setError(null);
      setSending(false);
    } else {
      dialogRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  const send = async () => {
    const alert = CANNED.find((c) => c.key === selected);
    if (!alert) return;
    setSending(true);
    setError(null);
    try {
      const res = await api<AlertResult>("/api/runs", {
        method: "POST",
        body: JSON.stringify({ version_label: candidate, input: alert.input }),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Send test alert"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="w-[520px] rounded-md border border-border-strong bg-surface-1 p-5 shadow-2xl outline-none"
      >
        <div className="mb-1 text-sm font-semibold">Send test alert</div>
        <p className="mb-4 text-xs text-text-3">
          Fires a real agent run against <Mono>{candidate}</Mono>: capture → judge → freeze on
          failure.
        </p>

        <div className="flex flex-col gap-1.5" role="radiogroup" aria-label="Canned alerts">
          {CANNED.map((c) => (
            <label
              key={c.key}
              className={`flex cursor-pointer items-center gap-2.5 rounded-md border px-3 py-2 text-[13px] transition-colors ${
                selected === c.key
                  ? "border-accent bg-accent-soft text-text-1"
                  : "border-border bg-surface-2 text-text-2 hover:bg-surface-3"
              }`}
            >
              <input
                type="radio"
                name="canned-alert"
                className="accent-[oklch(0.62_0.19_277)]"
                checked={selected === c.key}
                onChange={() => setSelected(c.key)}
              />
              {c.label}
            </label>
          ))}
        </div>

        {result ? (
          <div className="mt-4 rounded-md border border-border bg-surface-2 p-3">
            <div className="mb-1.5 flex items-center gap-2">
              <Badge tone={result.judge_passed ? "pass" : "block"}>
                judge: {result.judge_passed ? "PASS" : "FAIL"}
              </Badge>
              <Mono>{result.latency_ms}ms</Mono>
              {result.promoted_case_id ? (
                <Badge tone="warn">frozen into new eval case</Badge>
              ) : null}
            </div>
            <pre className="overflow-x-auto font-mono text-[11px] leading-relaxed text-text-2">
              {JSON.stringify(result.output, null, 2)}
            </pre>
            <div className="mt-2 flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  onClose();
                  router.push(`/traces/${result.run_id}`);
                }}
              >
                View trace
              </Button>
              {result.promoted_case_id ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    onClose();
                    router.push(`/evals/${result.promoted_case_id}`);
                  }}
                >
                  View frozen case
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="mt-3 rounded-md bg-block-soft px-3 py-2 font-mono text-xs text-block">
            {error}
          </div>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button variant="primary" onClick={() => void send()} disabled={sending}>
            {sending ? "Running agent…" : "Fire alert"}
          </Button>
        </div>
      </div>
    </div>
  );
}
