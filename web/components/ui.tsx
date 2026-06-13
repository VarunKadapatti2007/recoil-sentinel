"use client";

import { clsx } from "clsx";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import type { Severity, Verdict } from "@/lib/types";

/* tiny shadcn-ish ui bits wired to recoil's design tokens */

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx(
        "rounded-md border border-border bg-surface-1 shadow-[0_1px_0_0_oklch(1_0_0/3%)_inset]",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("flex items-center justify-between px-4 pt-3.5 pb-0", className)} {...props} />;
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={clsx("text-[11px] font-semibold uppercase tracking-[0.08em] text-text-3", className)}
      {...props}
    />
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("px-4 py-3.5", className)} {...props} />;
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  className,
  variant = "secondary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={clsx(
        "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        "disabled:cursor-not-allowed disabled:opacity-45",
        variant === "primary" &&
          "bg-accent text-[oklch(0.98_0_0)] hover:bg-[oklch(0.57_0.19_277)]",
        variant === "secondary" &&
          "border border-border-strong bg-surface-2 text-text-1 hover:bg-surface-3",
        variant === "ghost" && "text-text-2 hover:bg-surface-2 hover:text-text-1",
        variant === "danger" && "bg-block text-[oklch(0.98_0_0)] hover:opacity-90",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({
  className,
  tone = "neutral",
  children,
}: {
  className?: string;
  tone?: "neutral" | "accent" | "pass" | "block" | "warn";
  children: ReactNode;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-[5px] border px-1.5 py-px font-mono text-[10.5px] leading-[1.6]",
        tone === "neutral" && "border-border bg-surface-2 text-text-2",
        tone === "accent" && "border-[transparent] bg-accent-soft text-accent-text",
        tone === "pass" && "border-[transparent] bg-pass-soft text-pass",
        tone === "block" && "border-[transparent] bg-block-soft text-block",
        tone === "warn" && "border-[transparent] bg-warn-soft text-warn",
        className,
      )}
    >
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity, "neutral" | "warn" | "block" | "accent"> = {
  low: "neutral",
  medium: "accent",
  high: "warn",
  critical: "block",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEVERITY_TONE[severity]}>{severity}</Badge>;
}

export function VerdictPill({ verdict, large }: { verdict: Verdict; large?: boolean }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md font-mono font-semibold tracking-wide",
        large ? "px-4 py-1.5 text-xl" : "px-2 py-0.5 text-[11px]",
        verdict === "PASS" ? "bg-pass-soft text-pass" : "bg-block-soft text-block",
      )}
    >
      <span
        className={clsx(
          "inline-block rounded-full",
          large ? "size-2.5" : "size-1.5",
          verdict === "PASS" ? "bg-pass" : "bg-block",
        )}
      />
      {verdict}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-soft-pulse rounded-md bg-surface-2", className)} />;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-border py-14 text-center">
      <div className="text-sm font-medium text-text-2">{title}</div>
      {hint ? <div className="max-w-sm text-xs text-text-3">{hint}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-md border border-block/40 bg-block-soft/40 py-12 text-center">
      <div className="text-sm font-medium text-block">Couldn&apos;t load this view</div>
      <div className="max-w-md font-mono text-xs text-text-2">{message}</div>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function Th({ className, ...props }: HTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={clsx(
        "border-b border-border px-3 py-2 text-left text-[10.5px] font-semibold uppercase tracking-[0.08em] text-text-3",
        className,
      )}
      {...props}
    />
  );
}

export function Td({ className, ...props }: HTMLAttributes<HTMLTableCellElement>) {
  return <td className={clsx("border-b border-border/60 px-3 py-2 align-middle", className)} {...props} />;
}

export function Mono({ className, children }: { className?: string; children: ReactNode }) {
  return <span className={clsx("font-mono text-[12px] text-text-2", className)}>{children}</span>;
}
