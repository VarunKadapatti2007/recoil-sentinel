"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { gateStreamUrl, voiceUrl } from "@/lib/api";
import type { GateStreamCase, GateStreamVerdict } from "@/lib/types";
import { useVersions } from "@/components/version-context";
import { Badge, Button, Card, CardBody, Mono, SeverityBadge, Skeleton, VerdictPill } from "@/components/ui";

type Phase = "idle" | "running" | "done" | "error";

function CaseRow({ c }: { c: GateStreamCase }) {
  const regressed = c.kind === "regression";
  const fixed = c.kind === "newly_fixed";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className={`flex items-center gap-3 border-b border-border/60 px-4 py-2 ${
        regressed ? "bg-block-soft/50" : fixed ? "bg-pass-soft/40" : ""
      }`}
    >
      <motion.span
        initial={regressed ? { scale: 1.6 } : false}
        animate={{ scale: 1 }}
        className={`inline-block size-2.5 shrink-0 rounded-full ${
          c.candidate_passed ? "bg-pass" : "bg-block"
        }`}
        aria-hidden
      />
      <span className={`flex-1 text-[13px] ${regressed ? "font-semibold text-text-1" : "text-text-2"}`}>
        {c.title}
      </span>
      <SeverityBadge severity={c.severity} />
      <Mono className="w-28 text-right">
        {c.baseline_passed == null ? "—" : c.baseline_passed ? "pass" : "fail"} →{" "}
        <span className={c.candidate_passed ? "text-pass" : "text-block"}>
          {c.candidate_passed ? "pass" : "FAIL"}
        </span>
      </Mono>
      <span className="w-24 text-right">
        {regressed ? (
          <Badge tone="block">REGRESSION</Badge>
        ) : fixed ? (
          <Badge tone="pass">newly fixed</Badge>
        ) : (
          <span className="font-mono text-[10.5px] text-text-3">{c.from_cache ? "cached" : "live"}</span>
        )}
      </span>
    </motion.div>
  );
}

function GateScreen() {
  const search = useSearchParams();
  const router = useRouter();
  const { candidate: ctxCandidate, published, refresh } = useVersions();
  const candidate = search.get("candidate") ?? ctxCandidate;
  const autostart = search.get("autostart") === "1";

  const [phase, setPhase] = useState<Phase>("idle");
  const [cases, setCases] = useState<GateStreamCase[]>([]);
  const [verdict, setVerdict] = useState<GateStreamVerdict | null>(null);
  const [total, setTotal] = useState(0);
  const [baseline, setBaseline] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [publishMode, setPublishMode] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const startedRef = useRef(false);

  const start = useCallback(
    (withPublish: boolean) => {
      esRef.current?.close();
      setPhase("running");
      setCases([]);
      setVerdict(null);
      setStreamError(null);
      setPublishMode(withPublish);

      const es = new EventSource(gateStreamUrl(candidate, { publish: withPublish }));
      esRef.current = es;

      es.addEventListener("start", (e) => {
        const data = JSON.parse((e as MessageEvent).data);
        setTotal(data.total_cases);
        setBaseline(data.baseline);
      });
      es.addEventListener("case", (e) => {
        const data = JSON.parse((e as MessageEvent).data) as GateStreamCase;
        setCases((prev) => [...prev, data]);
      });
      es.addEventListener("verdict", (e) => {
        const data = JSON.parse((e as MessageEvent).data) as GateStreamVerdict;
        setVerdict(data);
        setPhase("done");
        es.close();
        void refresh();
        const audio = new Audio(voiceUrl(data.verdict));
        audio.play().catch(() => {
          /* voice layer is optional — silence is fine */
        });
      });
      es.addEventListener("error", (e) => {
        const me = e as MessageEvent;
        if (me.data) {
          setStreamError(JSON.parse(me.data).message);
          setPhase("error");
        } else if (esRef.current?.readyState === EventSource.CLOSED) {
          setStreamError("lost connection to the Recoil API (is `recoil serve` running on :8787?)");
          setPhase("error");
        }
        es.close();
      });
    },
    [candidate, refresh],
  );

  useEffect(() => {
    if (autostart && !startedRef.current) {
      startedRef.current = true;
      start(false);
    }
    return () => esRef.current?.close();
  }, [autostart, start]);

  const blocked = verdict?.verdict === "BLOCK";
  const regressedCases = cases.filter((c) => c.kind === "regression");

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-[15px] font-semibold">Publish gate</h1>
          <Badge tone="accent">candidate: {candidate}</Badge>
          <Badge>baseline: {baseline ?? published ?? "last published"}</Badge>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => start(false)} disabled={phase === "running"}>
            {phase === "running" ? "Gate running…" : "Run gate"}
          </Button>
          <Button variant="primary" onClick={() => start(true)} disabled={phase === "running"}>
            Attempt publish
          </Button>
        </div>
      </div>

      {phase === "idle" ? (
        <Card>
          <CardBody className="py-16 text-center">
            <div className="text-sm text-text-2">
              Run the regression suite for <Mono>{candidate}</Mono> against the published baseline.
            </div>
            <div className="mt-1 text-[12px] text-text-3">
              Every previously-fixed case must still pass — one regression blocks the publish.
            </div>
          </CardBody>
        </Card>
      ) : null}

      {phase === "error" ? (
        <Card className="border-block/40">
          <CardBody className="py-10 text-center">
            <div className="text-sm font-medium text-block">gate stream failed</div>
            <div className="mt-1 font-mono text-xs text-text-2">{streamError}</div>
            <Button className="mt-4" onClick={() => start(publishMode)}>
              Retry
            </Button>
          </CardBody>
        </Card>
      ) : null}

      {phase === "running" || phase === "done" ? (
        <Card>
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3">
              regression suite — {cases.length}/{total || "…"} cases
            </span>
            {phase === "running" ? (
              <span className="flex items-center gap-2 font-mono text-[11px] text-text-3">
                <span className="inline-block size-1.5 animate-soft-pulse rounded-full bg-accent" />
                judging
              </span>
            ) : null}
          </div>
          <div role="log" aria-live="polite">
            <AnimatePresence>
              {cases.map((c) => (
                <CaseRow key={c.case_id} c={c} />
              ))}
            </AnimatePresence>
            {phase === "running" && cases.length < total
              ? Array.from({ length: Math.min(3, total - cases.length) }).map((_, i) => (
                  <div key={`pending-${i}`} className="border-b border-border/60 px-4 py-2.5">
                    <Skeleton className="h-4 w-2/3" />
                  </div>
                ))
              : null}
          </div>
        </Card>
      ) : null}

      <AnimatePresence>
        {verdict ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.25 }}
          >
            <Card className={blocked ? "border-block/60" : "border-pass/50"}>
              <CardBody className="flex flex-col items-center gap-3 py-8">
                <VerdictPill verdict={verdict.verdict} large />
                <div className="font-mono text-[13px] text-text-2">
                  {verdict.passed_count}/{verdict.total_cases} passing · {verdict.regressed.length}{" "}
                  regression{verdict.regressed.length === 1 ? "" : "s"} ·{" "}
                  {verdict.newly_fixed.length} newly fixed
                </div>

                {blocked ? (
                  <div className="w-full max-w-xl rounded-md border border-block/40 bg-block-soft/40 p-4">
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-block">
                      publish refused — exit code 1
                    </div>
                    {regressedCases.map((c) => (
                      <div key={c.case_id} className="flex items-center justify-between gap-3 py-1">
                        <span className="text-[13px] text-text-1">{c.title}</span>
                        <Link
                          href={`/evals/${c.case_id}`}
                          className="shrink-0 text-[12px] text-accent-text underline-offset-2 hover:underline"
                        >
                          view diff →
                        </Link>
                      </div>
                    ))}
                    <p className="mt-2 text-[11.5px] leading-relaxed text-text-3">
                      This exact failure was fixed before — Recoil froze it as a permanent case and
                      just stopped it from shipping again.
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-2">
                    {verdict.published ? (
                      <Badge tone="pass">published — {candidate} is now the live agent</Badge>
                    ) : verdict.publish_attempted ? null : (
                      <Button variant="primary" onClick={() => start(true)}>
                        Publish {candidate}
                      </Button>
                    )}
                    <p className="text-[11.5px] text-text-3">
                      No regressions against {baseline}. Suite is green — clear to ship.
                    </p>
                  </div>
                )}

                <div className="mt-1 flex gap-3">
                  <Button variant="ghost" onClick={() => router.push("/")}>
                    Back to overview
                  </Button>
                  {blocked && regressedCases[0] ? (
                    <Button variant="secondary" onClick={() => router.push(`/evals/${regressedCases[0].case_id}`)}>
                      Open regression diff
                    </Button>
                  ) : null}
                </div>
              </CardBody>
            </Card>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export default function GatePage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <GateScreen />
    </Suspense>
  );
}
