"use client";

import Link from "next/link";
import { useFetch } from "@/lib/use-fetch";
import type { Overview } from "@/lib/types";
import { fmtAgo, fmtCost, fmtMs, fmtPct, shortId } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Mono,
  Skeleton,
  Td,
  Th,
  VerdictPill,
} from "@/components/ui";

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <Card>
      <CardBody>
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">
          {label}
        </div>
        <div className="mt-1.5 font-mono text-2xl font-semibold tracking-tight text-text-1">
          {value}
        </div>
        {sub ? <div className="mt-0.5 text-[11.5px] text-text-3">{sub}</div> : null}
      </CardBody>
    </Card>
  );
}

function PassRateSparkline({ points }: { points: { label: string; pass_rate: number }[] }) {
  if (points.length === 0) return <EmptyState title="No suite results yet" />;
  const w = 560;
  const h = 96;
  const pad = 8;
  const xs = points.map((_, i) => pad + (i * (w - 2 * pad)) / Math.max(points.length - 1, 1));
  const ys = points.map((p) => h - pad - p.pass_rate * (h - 2 * pad));
  const path = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x},${ys[i]}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h + 18}`} className="w-full" role="img" aria-label="Suite pass rate by version">
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2" />
      {xs.map((x, i) => (
        <g key={points[i].label}>
          <circle
            cx={x}
            cy={ys[i]}
            r="3.5"
            fill={points[i].pass_rate >= 1 ? "var(--pass)" : "var(--block)"}
          />
          <text x={x} y={h + 12} textAnchor="middle" fontSize="10" fill="var(--text-3)" fontFamily="var(--font-mono)">
            {points[i].label}
          </text>
          <text x={x} y={ys[i] - 8} textAnchor="middle" fontSize="10" fill="var(--text-2)" fontFamily="var(--font-mono)">
            {Math.round(points[i].pass_rate * 100)}%
          </text>
        </g>
      ))}
    </svg>
  );
}

export default function OverviewPage() {
  const { data, error, loading, reload } = useFetch<Overview>("/api/overview", 5000);

  if (loading && !data) {
    return (
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-44" />
        <Skeleton className="h-56" />
      </div>
    );
  }
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="No data" hint="Run `recoil reset --demo` to seed the system." />;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-4 gap-4">
        <Stat label="Production runs" value={data.total_runs.toLocaleString()} sub={`p95 latency ${fmtMs(data.p95_latency_ms)} · avg cost ${fmtCost(data.avg_cost_usd)}`} />
        <Stat label="Frozen eval cases" value={data.total_cases} sub={`${data.critical_cases} critical · grown from real failures`} />
        <Stat label="Suite pass rate" value={fmtPct(data.suite_pass_rate)} sub={`published: ${data.published_version ?? "—"}`} />
        <Card>
          <CardBody>
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">
              Last gate verdict
            </div>
            <div className="mt-2">
              {data.last_gate ? (
                <div className="flex items-center gap-2.5">
                  <VerdictPill verdict={data.last_gate.verdict} />
                  <span className="text-[11.5px] text-text-3">
                    {data.last_gate.candidate_label} · {fmtAgo(data.last_gate.created_at)}
                  </span>
                </div>
              ) : (
                <span className="text-sm text-text-3">no gate runs yet</span>
              )}
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Suite pass rate by agent version</CardTitle>
        </CardHeader>
        <CardBody>
          <PassRateSparkline points={data.version_pass_rates} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent gate runs</CardTitle>
        </CardHeader>
        <CardBody className="px-0 pb-0">
          {data.gate_runs.length === 0 ? (
            <div className="px-4 pb-4">
              <EmptyState title="No gate runs yet" hint="Pick a candidate version and press Run gate." />
            </div>
          ) : (
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <Th>id</Th>
                  <Th>candidate</Th>
                  <Th>baseline</Th>
                  <Th className="text-right">cases</Th>
                  <Th className="text-right">regressions</Th>
                  <Th>verdict</Th>
                  <Th>when</Th>
                </tr>
              </thead>
              <tbody>
                {data.gate_runs.map((g) => (
                  <tr key={g.id} className="hover:bg-surface-2/50">
                    <Td>
                      <Mono>{shortId(g.id)}</Mono>
                    </Td>
                    <Td>
                      <Badge tone="accent">{g.candidate_label}</Badge>
                    </Td>
                    <Td>
                      <Badge>{g.baseline_label}</Badge>
                    </Td>
                    <Td className="text-right">
                      <Mono>
                        {g.passed_count}/{g.total_cases}
                      </Mono>
                    </Td>
                    <Td className="text-right">
                      <Mono className={g.regressed_case_ids.length ? "text-block" : undefined}>
                        {g.regressed_case_ids.length}
                      </Mono>
                    </Td>
                    <Td>
                      <VerdictPill verdict={g.verdict} />
                    </Td>
                    <Td className="text-text-3">{fmtAgo(g.created_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>

      <div className="text-[11.5px] text-text-3">
        Every failure becomes a permanent test. Nothing regresses twice.{" "}
        <Link href="/evals" className="text-accent-text underline-offset-2 hover:underline">
          See how the suite grew itself →
        </Link>
      </div>
    </div>
  );
}
