"use client";

import Link from "next/link";
import { use } from "react";
import { useFetch } from "@/lib/use-fetch";
import type { RunDetail, Span } from "@/lib/types";
import { fmtCost, fmtMs, fmtTime } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  ErrorState,
  Mono,
  Skeleton,
} from "@/components/ui";

const SPAN_COLOR: Record<Span["type"], string> = {
  llm: "var(--accent)",
  tool: "var(--warn)",
  retrieval: "var(--pass)",
};

function Waterfall({ spans }: { spans: Span[] }) {
  const total = Math.max(...spans.map((s) => s.end_ms), 1);
  return (
    <div className="flex flex-col gap-1" role="list" aria-label="Span waterfall">
      <div className="mb-1 flex justify-between font-mono text-[10px] text-text-3">
        <span>0ms</span>
        <span>{fmtMs(total)}</span>
      </div>
      {spans.map((s, i) => {
        const left = (s.start_ms / total) * 100;
        const width = Math.max(((s.end_ms - s.start_ms) / total) * 100, 0.8);
        return (
          <div key={`${s.name}-${i}`} className="group grid grid-cols-[210px_1fr] items-center gap-3" role="listitem">
            <div className="flex items-center gap-1.5 overflow-hidden">
              <span
                className="inline-block size-2 shrink-0 rounded-[2px]"
                style={{ background: SPAN_COLOR[s.type] }}
                aria-hidden
              />
              <Mono className="truncate text-[11.5px]">{s.name}</Mono>
            </div>
            <div className="relative h-7 rounded-sm bg-surface-2">
              <div
                className="absolute top-1 h-5 rounded-sm opacity-90"
                style={{ left: `${left}%`, width: `${width}%`, background: SPAN_COLOR[s.type] }}
              />
              <div
                className="absolute top-1 flex h-5 items-center gap-2 whitespace-nowrap pl-1.5 font-mono text-[10.5px] text-text-2"
                style={{ left: `${Math.min(left + width, 78)}%` }}
              >
                <span>{fmtMs(s.end_ms - s.start_ms)}</span>
                {s.prompt_tokens != null ? (
                  <span className="text-text-3">
                    {s.prompt_tokens}→{s.completion_tokens} tok
                  </span>
                ) : null}
                {s.cost_usd != null ? <span className="text-text-3">{fmtCost(s.cost_usd)}</span> : null}
              </div>
            </div>
          </div>
        );
      })}
      <div className="mt-2 flex gap-4 font-mono text-[10.5px] text-text-3">
        {(Object.keys(SPAN_COLOR) as Span["type"][]).map((t) => (
          <span key={t} className="flex items-center gap-1.5">
            <span className="inline-block size-2 rounded-[2px]" style={{ background: SPAN_COLOR[t] }} />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function TraceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading, reload } = useFetch<RunDetail>(`/api/runs/${id}`);

  if (loading && !data)
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-64" />
        <Skeleton className="h-48" />
      </div>
    );
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Link href="/traces" className="text-[12px] text-text-3 hover:text-text-1">
          ← traces
        </Link>
        <h1 className="text-[15px] font-semibold">
          {String(data.input.title ?? data.input.message ?? "Trace")}
        </h1>
        <Badge tone="accent">{data.version_label}</Badge>
        <Mono>{data.id}</Mono>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {[
          ["latency", fmtMs(data.latency_ms)],
          ["total cost", fmtCost(data.total_cost_usd)],
          ["spans", String(data.spans.length)],
          ["captured", fmtTime(data.created_at)],
        ].map(([k, v]) => (
          <Card key={k}>
            <CardBody>
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">{k}</div>
              <div className="mt-1 font-mono text-lg text-text-1">{v}</div>
            </CardBody>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Span waterfall</CardTitle>
          {data.ground_truth_ref ? (
            <Mono className="text-[11px]">ground truth: {data.ground_truth_ref}</Mono>
          ) : null}
        </CardHeader>
        <CardBody>
          <Waterfall spans={data.spans} />
        </CardBody>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Input</CardTitle>
          </CardHeader>
          <CardBody>
            <pre className="overflow-x-auto font-mono text-[11.5px] leading-relaxed text-text-2">
              {JSON.stringify(data.input, null, 2)}
            </pre>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Structured output</CardTitle>
          </CardHeader>
          <CardBody>
            <pre className="overflow-x-auto font-mono text-[11.5px] leading-relaxed text-text-2">
              {JSON.stringify(data.output, null, 2)}
            </pre>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
