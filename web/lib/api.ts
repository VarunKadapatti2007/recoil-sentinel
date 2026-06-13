const API_BASE = process.env.NEXT_PUBLIC_RECOIL_API ?? "http://localhost:8787";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* no json body, just keep the statustext */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function gateStreamUrl(candidate: string, opts?: { baseline?: string; publish?: boolean }): string {
  const params = new URLSearchParams({ candidate });
  if (opts?.baseline) params.set("baseline", opts.baseline);
  if (opts?.publish) params.set("publish", "true");
  return `${API_BASE}/api/gate/stream?${params.toString()}`;
}

export function voiceUrl(verdict: "PASS" | "BLOCK"): string {
  return `${API_BASE}/api/voice/${verdict}`;
}

export interface VerificationRun {
  domain: "market" | "wallet";
  verdict: "PASS" | "BLOCK";
  subject_label: string;
  title: string;
  claims_verified: string;
  injected_fault: string | null;
  problems: string[];
  run_id: string;
  cost_usd?: number;
  published?: boolean;
  report_url?: string | null;
  integrations?: Record<string, string>;
  ground_truth: { key: string; label: string; value: number; unit: string; source: string; source_url: string }[];
  findings: {
    headline: string;
    body: string;
    metric_keys: string[];
    claimed_values: Record<string, number>;
    signal: "bullish" | "bearish" | "neutral" | "risk";
  }[];
  verification: {
    passed: boolean;
    problems: string[];
    checks: {
      finding_index: number;
      metric_key: string;
      claimed: number | null;
      observed: number | null;
      ok: boolean;
      problem: string;
    }[];
  };
}

export async function runMarketVerification(focus: string, tamper: boolean): Promise<VerificationRun> {
  const params = new URLSearchParams();
  if (focus.trim()) params.set("focus", focus.trim());
  if (tamper) params.set("tamper", "true");
  return api<VerificationRun>(`/api/sentinel/run?${params.toString()}`, { method: "POST" });
}

export async function runWalletVerification(tamper: boolean): Promise<VerificationRun> {
  const params = new URLSearchParams();
  if (tamper) params.set("tamper", "true");
  return api<VerificationRun>(`/api/wallet/verify?${params.toString()}`, { method: "POST" });
}
