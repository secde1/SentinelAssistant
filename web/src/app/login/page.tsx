"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { IconLock, IconShield } from "@/components/icons";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(value: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/login", { token: value.trim() });
      router.replace("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  useEffect(() => {
    document.title = "Sign in · SENTINAL Control Center";
    // dashboard.cmd brauzerni /login/#t=<token> bilan ochadi: fragment serverga yuborilmaydi va darhol o'chiriladi.
    const m = window.location.hash.match(/[#&]t=([^&]+)/);
    if (m) {
      window.history.replaceState(null, "", window.location.pathname);
      api.post("/api/login", { token: decodeURIComponent(m[1]).trim() })
        .then(() => router.replace("/"))
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    } else {
      api.get("/api/session").then(() => router.replace("/")).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-2xl border border-line bg-surface p-8">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <IconShield width={22} height={22} />
          </span>
          <div>
            <div className="text-base font-semibold tracking-wide">SENTINAL</div>
            <div className="text-[11px] font-medium tracking-[0.2em] text-ink-3">CONTROL CENTER</div>
          </div>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); signIn(token); }} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-xs text-ink-3">
            Access token
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus
              autoComplete="current-password"
              className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink" />
          </label>
          {error ? <div className="text-sm text-critical">{error}</div> : null}
          <button type="submit" disabled={busy || !token.trim()}
            className="mt-1 inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50">
            <IconLock width={16} height={16} /> {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-6 text-xs leading-relaxed text-ink-3">
          Open the dashboard with <span className="font-mono text-ink-2">dashboard.cmd</span> to sign in automatically.
          The token is stored in <span className="font-mono text-ink-2">data\ish\dashboard.json</span> on this computer.
        </p>
      </div>
    </div>
  );
}
