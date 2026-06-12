"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";
import type { CaseDiff, EvalCaseDetail } from "@/lib/types";
import { fmtTime } from "@/lib/format";
import { useVersions } from "@/components/version-context";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  ErrorState,
  Mono,
  SeverityBadge,
  Skeleton,
} from "@/components/ui";

function FieldValue({ value, changed, side }: { value: unknown; changed: boolean; side: "baseline" | "candidate" }) {
  const display = typeof value === "string" ? value : JSON.stringify(value);
  return (
    <span
      className={
        changed
          ? side === "baseline"
            ? "rounded-sm bg-pass-soft px-1.5 py-0.5 font-mono text-[12.5px] text-pass"
            : "rounded-sm bg-block-soft px-1.5 py-0.5 font-mono text-[12.5px] font-semibold text-block"
          : "font-mono text-[12.5px] text-text-2"
      }
    >
      {display}
    </span>
  );
}

function DiffPanel({ diff }: { diff: CaseDiff }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Regression diff — <span className="normal-case">{diff.baseline.label} → {diff.candidate.label}</span>
        </CardTitle>
        <div className="flex gap-2 pb-1">
          <Badge tone={diff.baseline.passed ? "pass" : "block"}>
            {diff.baseline.label}: {diff.baseline.passed ? "PASS" : "FAIL"}
          </Badge>
          <Badge tone={diff.candidate.passed ? "pass" : "block"}>
            {diff.candidate.label}: {diff.candidate.passed ? "PASS" : "FAIL"}
          </Badge>
        </div>
      </CardHeader>
      <CardBody className="px-0 pb-0">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th className="w-36 border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
                field
              </th>
              <th className="border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-pass">
                {diff.baseline.label} (baseline)
              </th>
              <th className="border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-block">
                {diff.candidate.label} (candidate)
              </th>
            </tr>
          </thead>
          <tbody>
            {diff.fields.map((f) => (
              <tr key={f.field} className={f.changed ? "bg-block-soft/30" : undefined}>
                <td className="border-b border-border/60 px-4 py-2.5">
                  <Mono className={f.changed ? "font-semibold text-text-1" : undefined}>{f.field}</Mono>
                  {f.changed ? (
                    <Badge tone="block" className="ml-2">
                      changed
                    </Badge>
                  ) : null}
                </td>
                <td className="border-b border-border/60 px-4 py-2.5">
                  <FieldValue value={f.baseline} changed={f.changed} side="baseline" />
                </td>
                <td className="border-b border-border/60 px-4 py-2.5">
                  <FieldValue value={f.candidate} changed={f.changed} side="candidate" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="grid grid-cols-2 gap-0 border-t border-border">
          <div className="border-r border-border px-4 py-3">
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
              judge rationale — baseline
            </div>
            <p className="text-[12.5px] leading-relaxed text-text-2">{diff.baseline.rationale}</p>
          </div>
          <div className="px-4 py-3">
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
              judge rationale — candidate
            </div>
            <p className="text-[12.5px] leading-relaxed text-text-2">{diff.candidate.rationale}</p>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

export default function EvalCaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { candidate, published } = useVersions();
  const { data: caseData, error, loading, reload } = useFetch<EvalCaseDetail>(`/api/eval-cases/${id}`);
  const [diff, setDiff] = useState<CaseDiff | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);

  const baseline = published ?? "v_good";

  useEffect(() => {
    if (!baseline || !candidate || baseline === candidate) {
      setDiff(null);
      return;
    }
    let alive = true;
    setDiffError(null);
    api<CaseDiff>(
      `/api/eval-cases/${id}/diff?baseline=${encodeURIComponent(baseline)}&candidate=${encodeURIComponent(candidate)}`,
    )
      .then((d) => {
        if (alive) setDiff(d);
      })
      .catch((e) => {
        if (alive) {
          setDiff(null);
          setDiffError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      alive = false;
    };
  }, [id, baseline, candidate]);

  if (loading && !caseData)
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-96" />
        <Skeleton className="h-72" />
        <Skeleton className="h-48" />
      </div>
    );
  if (error && !caseData) return <ErrorState message={error} onRetry={reload} />;
  if (!caseData) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Link href="/evals" className="text-[12px] text-text-3 hover:text-text-1">
          ← eval suite
        </Link>
        <h1 className="text-[15px] font-semibold">{caseData.title}</h1>
        <SeverityBadge severity={caseData.severity} />
        {caseData.first_failed_label ? (
          <Badge tone="block">first failed: {caseData.first_failed_label}</Badge>
        ) : null}
        {caseData.fixed_in_label ? <Badge tone="pass">fixed in: {caseData.fixed_in_label}</Badge> : null}
      </div>

      {diff ? (
        <DiffPanel diff={diff} />
      ) : (
        <Card>
          <CardBody className="text-[12.5px] text-text-3">
            {baseline === candidate
              ? `Candidate is the published baseline (${baseline}) — pick a different candidate in the top bar to see a diff.`
              : diffError
                ? `No diff available: ${diffError}`
                : "Loading diff…"}
          </CardBody>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Frozen input</CardTitle>
          </CardHeader>
          <CardBody>
            <pre className="overflow-x-auto font-mono text-[11.5px] leading-relaxed text-text-2">
              {JSON.stringify(caseData.input, null, 2)}
            </pre>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Ground-truth context snapshot</CardTitle>
            <Mono className="text-[11px] lowercase">
              {String(caseData.context_snapshot.ground_truth_source ?? "")}
            </Mono>
          </CardHeader>
          <CardBody>
            <pre className="overflow-x-auto font-mono text-[11.5px] leading-relaxed text-text-2">
              {JSON.stringify(
                { expected: caseData.context_snapshot.expected, constraints: caseData.context_snapshot.constraints },
                null,
                2,
              )}
            </pre>
            <div className="mt-3 border-t border-border pt-3">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
                rubric
              </div>
              <p className="text-[12px] leading-relaxed text-text-2">{caseData.rubric}</p>
              <div className="mb-1 mt-3 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">
                reference behavior
              </div>
              <p className="text-[12px] leading-relaxed text-text-2">{caseData.reference_behavior}</p>
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Verdict history across versions</CardTitle>
        </CardHeader>
        <CardBody className="px-0 pb-0">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                <th className="border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">version</th>
                <th className="border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">verdict</th>
                <th className="border-b border-border px-4 py-2 text-right text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">score</th>
                <th className="border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">judge rationale</th>
                <th className="border-b border-border px-4 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3">judged</th>
              </tr>
            </thead>
            <tbody>
              {caseData.results.map((r) => (
                <tr key={r.id} className="align-top hover:bg-surface-2/50">
                  <td className="border-b border-border/60 px-4 py-2.5">
                    <Badge tone="accent">{r.version_label}</Badge>
                  </td>
                  <td className="border-b border-border/60 px-4 py-2.5">
                    <Badge tone={r.passed ? "pass" : "block"}>{r.passed ? "PASS" : "FAIL"}</Badge>
                  </td>
                  <td className="border-b border-border/60 px-4 py-2.5 text-right">
                    <Mono>{r.score.toFixed(2)}</Mono>
                  </td>
                  <td className="max-w-[440px] border-b border-border/60 px-4 py-2.5 text-[12px] leading-relaxed text-text-2">
                    {r.judge_rationale}
                  </td>
                  <td className="whitespace-nowrap border-b border-border/60 px-4 py-2.5 text-[11.5px] text-text-3">
                    {fmtTime(r.created_at)}
                    {r.from_cache ? <Badge className="ml-1.5">cached</Badge> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>
    </div>
  );
}
