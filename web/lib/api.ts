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
      /* keep statusText */
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
