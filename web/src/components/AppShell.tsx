"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import {
  IconBell, IconBot, IconChart, IconCollapse, IconDashboard, IconFlask, IconLayers, IconLogout, IconMenu, IconPulse,
  IconReport, IconSettings, IconShield, IconSun, IconTrend,
} from "./icons";
import { Dot, ToastProvider } from "./kit";

const NAV = [
  { href: "/dashboard/", label: "Dashboard", icon: IconDashboard },
  { href: "/desk/", label: "Trading bo'limi", icon: IconBot },
  { href: "/chart/", label: "Grafik", icon: IconChart },
  { href: "/zones/", label: "Zonalar", icon: IconLayers },
  { href: "/signals/", label: "Signallar", icon: IconTrend },
  { href: "/positions/", label: "Pozitsiyalar", icon: IconPulse },
  { href: "/control/", label: "Boshqaruv", icon: IconShield },
  { href: "/trading/", label: "Trading Research", icon: IconFlask },
  { href: "/agents/", label: "Agentlar", icon: IconBot },
  { href: "/reports/", label: "Hisobotlar", icon: IconReport },
  { href: "/diagnostics/", label: "Diagnostika", icon: IconPulse },
  { href: "/settings/", label: "Sozlamalar", icon: IconSettings },
];

export interface SysStatus {
  agent: { running: boolean; busy: boolean; version: string | null };
  mt5: { connected: boolean | null; last: string | null };
  telegram: { active: boolean; last_send?: string | null };
  research: { last_job: string | null; status: string | null; fresh?: boolean };
  last_sync: string | null;
  server_time: string;
}

function isActive(pathname: string, href: string) {
  return pathname.startsWith(href.replace(/\/$/, ""));
}

function safe(fn: () => void) {
  try { fn(); } catch { /* brauzer xotirasi yopiq bo'lishi mumkin */ }
}

function Pill({ label, value, on }: { label: string; value: string; on: boolean | null }) {
  return (
    <div className="hidden items-center gap-2 border-l border-line pl-4 first:border-0 first:pl-0 xl:flex">
      <Dot on={on} pulse />
      <div className="leading-tight">
        <div className="text-[11px] font-semibold">{label}</div>
        <div className="text-[10px] text-ink-3">{value}</div>
      </div>
    </div>
  );
}

function Bell() {
  const [open, setOpen] = useState(false);
  const msgs = useApi<{ items: { id: number; ts: string; role: string; kind: string; text: string }[] }>(open ? "/api/desk/messages" : null, 15000);
  const items = (msgs.data?.items ?? []).filter((m) => m.kind === "verdict" || m.kind === "system" || m.kind === "audit").slice(-8).reverse();
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-label="Bildirishnomalar" className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink"><IconBell /></button>
      {open ? (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-2 w-80 rounded-xl border border-line bg-surface p-2 shadow-2xl">
            <div className="px-2 py-1.5 text-xs font-semibold text-ink-3">So&apos;nggi qarorlar va xabarlar</div>
            {!items.length ? <div className="px-2 py-6 text-center text-xs text-ink-3">{msgs.loading ? "Yuklanmoqda…" : "Hali xabar yo'q"}</div> : items.map((m) => (
              <div key={m.id} className="rounded-lg px-2 py-2 text-xs hover:bg-surface-2">
                <div className="font-mono text-[11px] text-accent">{m.role} <span className="text-ink-3">· {ago(m.ts)}</span></div>
                <div className="mt-0.5 line-clamp-2 text-ink-2">{m.text}</div>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [light, setLight] = useState(false);
  const [menu, setMenu] = useState(false);
  const [authed, setAuthed] = useState(false);
  const isLogin = pathname.startsWith("/login");
  const st = useApi<SysStatus>(authed ? "/api/desk/status" : null, 10000);

  useEffect(() => {
    safe(() => {
      setCollapsed(localStorage.getItem("sx-collapsed") === "1");
      const t = localStorage.getItem("sx-theme") === "light";
      setLight(t);
      document.documentElement.dataset.theme = t ? "light" : "dark";
    });
  }, []);

  useEffect(() => {
    if (isLogin) return;
    api.get("/api/session").then(() => setAuthed(true)).catch(() => {});
  }, [isLogin]);

  if (isLogin) return <>{children}</>;

  function toggleCollapse() {
    setCollapsed(!collapsed);
    safe(() => localStorage.setItem("sx-collapsed", collapsed ? "0" : "1"));
  }
  function toggleTheme() {
    const next = !light;
    setLight(next);
    document.documentElement.dataset.theme = next ? "light" : "dark";
    safe(() => localStorage.setItem("sx-theme", next ? "light" : "dark"));
  }
  async function logout() {
    try { await api.post("/api/logout"); } finally { router.replace("/login/"); }
  }

  const s = st.data;
  const w = collapsed ? "lg:w-[68px]" : "lg:w-60";
  return (
    <ToastProvider>
      <div className="flex min-h-screen">
        <aside className={`no-print fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-line bg-surface transition-[transform,width] duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${w} ${open ? "translate-x-0" : "-translate-x-full"}`}>
          <div className="flex h-16 items-center gap-2.5 border-b border-line px-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent"><IconShield width={20} height={20} /></span>
            <div className={`leading-tight ${collapsed ? "lg:hidden" : ""}`}>
              <div className="text-sm font-bold tracking-[0.14em]">SENTINEL</div>
              <div className="text-[10px] font-medium tracking-[0.2em]" style={{ color: "var(--accent-2)" }}>AI TRADING</div>
            </div>
          </div>
          <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2.5" aria-label="Main">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = isActive(pathname, href);
              return (
                <Link key={href} href={href} onClick={() => setOpen(false)} title={label}
                  className={`group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all ${active ? "bg-accent text-white shadow-lg shadow-accent/20" : "text-ink-2 hover:translate-x-0.5 hover:bg-surface-2 hover:text-ink"} ${collapsed ? "lg:justify-center lg:px-0" : ""}`}
                  aria-current={active ? "page" : undefined}>
                  <Icon className={`shrink-0 ${active ? "text-white" : "text-ink-3 group-hover:text-accent"}`} />
                  <span className={collapsed ? "lg:hidden" : ""}>{label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="border-t border-line p-3">
            <div className={`mb-2 flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2 text-[11px] ${collapsed ? "lg:justify-center lg:px-0" : ""}`}>
              <Dot on={s ? s.agent.running : null} pulse />
              <div className={`leading-tight ${collapsed ? "lg:hidden" : ""}`}>
                <div className="font-medium">{s ? (s.agent.running ? "Server: online" : "Server: agent o'chiq") : "Server: N/A"}</div>
                <div className="text-ink-3">v{s?.agent.version ?? "—"} · 127.0.0.1</div>
              </div>
            </div>
            <button onClick={toggleCollapse} title="Menyuni yig'ish / ochish"
              className="hidden w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink lg:flex">
              <IconCollapse className="shrink-0 text-ink-3" /><span className={collapsed ? "lg:hidden" : ""}>Yig&apos;ish</span>
            </button>
          </div>
        </aside>
        {open ? <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={() => setOpen(false)} /> : null}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="no-print sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-line bg-page/85 px-4 backdrop-blur md:px-6">
            <button className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 lg:hidden" onClick={() => setOpen(true)} aria-label="Menyuni ochish"><IconMenu /></button>
            <Pill label="SENTINEL AI" value={s ? (s.agent.running ? (s.agent.busy ? "WORKING" : "ONLINE") : "OFFLINE") : "N/A"} on={s ? s.agent.running : null} />
            <Pill label="MT5" value={s ? (s.mt5.connected === null ? "N/A" : s.mt5.connected ? "Connected" : "Stale") : "N/A"} on={s ? s.mt5.connected : null} />
            <Pill label="Telegram Bot" value={s ? (s.telegram.active ? (s.telegram.last_send ? `agent ishlayapti · yuborish ${ago(s.telegram.last_send)}` : "agent ishlayapti") : "Offline") : "N/A"} on={s ? s.telegram.active : null} />
            <Pill label="Research Engine" value={s?.research.last_job ? `oxirgi ish ${s.research.status ?? "?"} · ${ago(s.research.last_job)}` : "N/A"} on={s?.research.last_job ? !!s.research.fresh : null} />
            <div className="ml-auto flex items-center gap-1">
              <div className="mr-2 hidden text-right leading-tight lg:block">
                <div className="text-[10px] uppercase tracking-wide text-ink-3">Oxirgi sinxronizatsiya</div>
                <div className="text-xs">{s?.last_sync ? ago(s.last_sync) : "N/A"}</div>
              </div>
              <button onClick={toggleTheme} aria-label="Mavzuni almashtirish" title={light ? "Qorong'i mavzu" : "Yorug' mavzu"} className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink"><IconSun /></button>
              <Bell />
              <div className="relative">
                <button onClick={() => setMenu(!menu)} aria-label="Profil" className="ml-1 flex h-8 w-8 items-center justify-center rounded-full bg-accent/20 text-xs font-bold text-accent">J</button>
                {menu ? (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setMenu(false)} />
                    <div className="absolute right-0 z-40 mt-2 w-48 rounded-xl border border-line bg-surface p-1.5 shadow-2xl">
                      <div className="px-3 py-2 text-xs text-ink-3">Egasi · lokal sessiya</div>
                      <button onClick={logout} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"><IconLogout /> Chiqish</button>
                    </div>
                  </>
                ) : null}
              </div>
            </div>
          </header>
          <main className="print-full mx-auto w-full max-w-[1760px] flex-1 px-4 py-5 md:px-6">
            {authed ? children : <div className="py-24 text-center text-sm text-ink-3">Sessiya tekshirilmoqda…</div>}
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
