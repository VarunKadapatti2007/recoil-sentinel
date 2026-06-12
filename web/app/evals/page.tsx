"use client";

import Link from "next/link";
import { useFetch } from "@/lib/use-fetch";
import type { EvalCase } from "@/lib/types";
import { fmtAgo } from "@/lib/format";
import {
  Badge,
  Card,
  CardBody,
  EmptyState,
  ErrorState,
  Mono,
  SeverityBadge,
  Skeleton,
} from "@/components/ui";

export default function EvalsPage() {
  const { data, error, loading, reload } = useFetch<EvalCase[]>("/api/eval-cases", 8000);

  if (loading && !data)
    return (
      <div className="grid grid-cols-3 gap-4">
        {Array.from({ length: 9 }).map((_, i) => (
          <Skeleton key={i} className="h-40" />
        ))}
      </div>
    );
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data || data.length === 0)
    return (
      <EmptyState
        title="The suite is empty"
        hint="Eval cases are frozen automatically from judged failures — send a failing test alert to grow the suite."
      />
    );

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-2xl text-[12.5px] text-text-3">
        Every case below was frozen from a <span className="text-text-2">real judged failure</span> in
        production — the suite grew itself. A case is never deleted: once fixed, it guards that
        behavior forever.
      </p>
      <div className="grid grid-cols-3 gap-4">
        {data.map((c) => (
          <Link
            key={c.id}
            href={`/evals/${c.id}`}
            className="group focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <Card className="h-full transition-colors group-hover:border-border-strong group-hover:bg-surface-2/60">
              <CardBody className="flex h-full flex-col gap-2.5">
                <div className="flex items-start justify-between gap-2">
                  <SeverityBadge severity={c.severity} />
                  {c.status === "muted" ? <Badge>muted</Badge> : null}
                </div>
                <div className="text-[13.5px] font-medium leading-snug text-text-1">{c.title}</div>
                <div className="mt-auto flex flex-col gap-1.5">
                  <div className="flex flex-wrap gap-1.5">
                    {c.first_failed_label ? (
                      <Badge tone="block">first failed: {c.first_failed_label}</Badge>
                    ) : null}
                    {c.fixed_in_label ? (
                      <Badge tone="pass">fixed in: {c.fixed_in_label}</Badge>
                    ) : (
                      <Badge tone="warn">unfixed</Badge>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <Mono className="text-[10.5px]">
                      {c.ground_truth_source ?? "context snapshot"}
                    </Mono>
                    <span className="text-[10.5px] text-text-3">{fmtAgo(c.created_at)}</span>
                  </div>
                </div>
              </CardBody>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
