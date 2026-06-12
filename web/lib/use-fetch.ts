"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

interface FetchState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useFetch<T>(path: string, intervalMs?: number): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const result = await api<T>(path);
      if (alive.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    void load();
    let timer: ReturnType<typeof setInterval> | undefined;
    if (intervalMs) timer = setInterval(() => void load(), intervalMs);
    return () => {
      alive.current = false;
      if (timer) clearInterval(timer);
    };
  }, [load, intervalMs]);

  return { data, error, loading, reload: () => void load() };
}
