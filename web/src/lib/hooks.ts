"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { api } from "./api";

/** GET so'rov; `intervalMs` berilsa — davriy yangilanadi (sahifa yashirin bo'lsa to'xtaydi). */
export function useApi<T>(path: string | null, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const pathRef = useRef(path);

  const load = useCallback(async () => {
    const p = pathRef.current;
    if (!p) return;
    try {
      const d = await api.get<T>(p);
      if (pathRef.current === p) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (pathRef.current === p) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (pathRef.current === p) setLoading(false);
    }
  }, []);

  useEffect(() => {
    pathRef.current = path;
    load();
    if (!intervalMs) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, intervalMs);
    return () => clearInterval(id);
  }, [path, intervalMs, load]);

  return { data, error, loading, reload: load };
}

/** URL query parametrlari (statik eksportda useSearchParams o'rniga — faqat brauzerda o'qiladi). */
function subscribeLocation(cb: () => void) {
  window.addEventListener("popstate", cb);
  return () => window.removeEventListener("popstate", cb);
}

export function useQuery(): URLSearchParams | null {
  const search = useSyncExternalStore(subscribeLocation, () => window.location.search, () => null);
  return useMemo(() => (search === null ? null : new URLSearchParams(search)), [search]);
}

/** Brauzerdagi joriy query (faqat klientda, birinchi renderda bir marta o'qish uchun). */
export function readQuery(): URLSearchParams {
  return new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
}

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · SENTINAL Control Center`;
  }, [title]);
}
