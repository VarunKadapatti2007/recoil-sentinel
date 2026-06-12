"use client";

import Link from "next/link";
import { useFetch } from "@/lib/use-fetch";
import type { RunSummary } from "@/lib/types";
import { fmtAgo, fmtCost, fmtMs, shortId } from "@/lib/format";
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
} from "@/components/ui";

export default function TracesPage() {
  const { data, error, loading, reload } = useFetch<{ items: RunSummary[]; total: number }>(
    "/api/runs?limit=60",
    6000,
  );

  if (loading && !data) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-[480px]" />
      </div>
    );
  }
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data || data.items.length === 0)
    return (
      <EmptyState
        title="No traces captured yet"
        hint="Send a test alert from the top bar, or run `recoil run` from the CLI."
      />
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Production runs <span className="normal-case text-text-3">({data.total} captured)</span>
        </CardTitle>
      </CardHeader>
      <CardBody className="px-0 pb-0">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <Th>trace</Th>
              <Th>input</Th>
              <Th>version</Th>
              <Th>queue → priority</Th>
              <Th className="text-right">latency</Th>
              <Th className="text-right">cost</Th>
              <Th className="text-right">spans</Th>
              <Th>when</Th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) => (
              <tr key={r.id} className="hover:bg-surface-2/50">
                <Td>
                  <Link
                    href={`/traces/${r.id}`}
                    className="font-mono text-[12px] text-accent-text underline-offset-2 hover:underline"
                  >
                    {shortId(r.id)}
                  </Link>
                </Td>
                <Td className="max-w-[300px] truncate text-text-2">
                  {String(r.input.title ?? r.input.message ?? "—")}
                </Td>
                <Td>
                  <Badge tone="accent">{r.version_label}</Badge>
                </Td>
                <Td>
                  <Mono>
                    {String(r.output.queue ?? "—")} → {String(r.output.priority ?? "—")}
                  </Mono>
                  {r.output.escalate === true ? (
                    <Badge tone="warn" className="ml-1.5">
                      escalated
                    </Badge>
                  ) : null}
                </Td>
                <Td className="text-right">
                  <Mono>{fmtMs(r.latency_ms)}</Mono>
                </Td>
                <Td className="text-right">
                  <Mono>{fmtCost(r.total_cost_usd)}</Mono>
                </Td>
                <Td className="text-right">
                  <Mono>{r.span_count}</Mono>
                </Td>
                <Td className="whitespace-nowrap text-text-3">{fmtAgo(r.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}
