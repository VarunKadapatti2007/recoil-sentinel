"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { VersionInfo } from "@/lib/types";

interface VersionState {
  versions: VersionInfo[];
  candidate: string;
  setCandidate: (label: string) => void;
  published: string | null;
  refresh: () => Promise<void>;
  loading: boolean;
}

const Ctx = createContext<VersionState | null>(null);

const DEMO_VERSIONS = new Set(["v_good", "v_regressed", "v_fixed"]);

export function VersionProvider({ children }: { children: ReactNode }) {
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [candidate, setCandidateState] = useState<string>("v_regressed");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const all = await api<VersionInfo[]>("/api/versions");
      setVersions(all.filter((v) => DEMO_VERSIONS.has(v.label)));
    } catch {
      setVersions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const stored = window.localStorage.getItem("recoil.candidate");
    if (stored) setCandidateState(stored);
    void refresh();
  }, [refresh]);

  const setCandidate = useCallback((label: string) => {
    setCandidateState(label);
    window.localStorage.setItem("recoil.candidate", label);
  }, []);

  const published = versions.find((v) => v.is_published)?.label ?? null;

  return (
    <Ctx.Provider value={{ versions, candidate, setCandidate, published, refresh, loading }}>
      {children}
    </Ctx.Provider>
  );
}

export function useVersions(): VersionState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useVersions must be used within VersionProvider");
  return ctx;
}
