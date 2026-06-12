"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Badge, Button } from "@/components/ui";
import { useVersions } from "@/components/version-context";
import { TestAlertDialog } from "@/components/test-alert";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/verify", label: "Verify (live)" },
  { href: "/traces", label: "Traces" },
  { href: "/evals", label: "Eval suite" },
  { href: "/gate", label: "Gate / Publish" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { versions, candidate, setCandidate, published, loading } = useVersions();
  const [alertOpen, setAlertOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-20 flex w-52 flex-col border-r border-border bg-surface-1/60">
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <span className="inline-block size-2.5 rounded-[3px] bg-accent" aria-hidden />
          <span className="text-[15px] font-semibold tracking-tight">Recoil</span>
          <span className="mt-px font-mono text-[10px] uppercase tracking-wider text-text-3">
            agent ci
          </span>
        </div>
        <nav className="flex flex-col gap-0.5 p-2" aria-label="Primary">
          {NAV.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={clsx(
                  "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                  active
                    ? "bg-accent-soft text-accent-text"
                    : "text-text-2 hover:bg-surface-2 hover:text-text-1",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto border-t border-border p-3 text-[11px] text-text-3">
          <div className="flex items-center justify-between">
            <span>published</span>
            <Badge tone="pass">{published ?? "—"}</Badge>
          </div>
        </div>
      </aside>

      <div className="ml-52 flex min-h-screen flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-border bg-bg/90 px-5 backdrop-blur">
          <div className="text-[13px] text-text-3">
            {NAV.find((n) =>
              n.href === "/" ? pathname === "/" : pathname.startsWith(n.href),
            )?.label ?? ""}
          </div>
          <div className="flex items-center gap-2.5">
            <Button variant="secondary" onClick={() => setAlertOpen(true)}>
              Send test alert
            </Button>
            <label className="flex items-center gap-2 text-[12px] text-text-3">
              candidate
              <select
                aria-label="Candidate agent version"
                className="h-8 rounded-md border border-border-strong bg-surface-2 px-2 font-mono text-[12px] text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                value={candidate}
                disabled={loading}
                onChange={(e) => setCandidate(e.target.value)}
              >
                {versions.map((v) => (
                  <option key={v.id} value={v.label}>
                    {v.label}
                    {v.is_published ? " (published)" : ""}
                  </option>
                ))}
                {versions.length === 0 ? <option value={candidate}>{candidate}</option> : null}
              </select>
            </label>
            <Button
              variant="primary"
              disabled={loading}
              onClick={() => router.push(`/gate?candidate=${encodeURIComponent(candidate)}&autostart=1`)}
            >
              Run gate
            </Button>
          </div>
        </header>
        <main className="flex-1 px-5 py-5">{children}</main>
      </div>

      <TestAlertDialog open={alertOpen} onClose={() => setAlertOpen(false)} />
    </div>
  );
}
