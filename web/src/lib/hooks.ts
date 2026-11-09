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


const mem = new Map<string, string>();  // localStorage yopiq bo'lsa ham qiymat sessiya ichida saqlanadi
const subs = new Set<() => void>();
function subscribeStore(cb: () => void) {
  subs.add(cb);
  window.addEventListener("storage", cb);
  return () => { subs.delete(cb); window.removeEventListener("storage", cb); };
}

/** Brauzer xotirasida saqlanadigan holat (SSR-xavfsiz: serverda va birinchi renderda `fallback`). Faqat per-viewer qulaylik uchun. */
export function usePersisted<T>(key: string, fallback: T): [T, (v: T) => void] {
  const raw = useSyncExternalStore(
    subscribeStore,
    () => { const m = mem.get(key); if (m !== undefined) return m; try { return localStorage.getItem(key); } catch { return null; } },
    () => null,
  );
  const value = useMemo<T>(() => { if (raw === null) return fallback; try { return JSON.parse(raw) as T; } catch { return fallback; } }, [raw, fallback]);
  const set = useCallback((v: T) => {
    const text = JSON.stringify(v);
    mem.set(key, text);
    try { localStorage.setItem(key, text); } catch { /* xotira yopiq — mem ishlaydi */ }
    subs.forEach((f) => f());
  }, [key]);
  return [value, set];
}
