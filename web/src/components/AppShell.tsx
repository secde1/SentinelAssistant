"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { AgentStatus } from "@/lib/types";
import {
  IconBuilding, IconChat, IconDashboard, IconHistory, IconLayers, IconLogout, IconMenu, IconMonitor, IconPulse,
  IconReport, IconSettings, IconShield, IconTrend,
} from "./icons";

const NAV = [
  { href: "/", label: "Dashboard", icon: IconDashboard },
  { href: "/organizations/", label: "Organizations", icon: IconBuilding },
  { href: "/departments/", label: "Departments", icon: IconLayers },
  { href: "/devices/", label: "Devices", icon: IconMonitor },
  { href: "/monitoring/", label: "Monitoring", icon: IconPulse },
  { href: "/activity/", label: "Activity History", icon: IconHistory },
  { href: "/trading/", label: "Trading Research", icon: IconTrend },
  { href: "/chat/", label: "AI Chat", icon: IconChat },
  { href: "/reports/", label: "Reports", icon: IconReport },
  { href: "/settings/", label: "Settings", icon: IconSettings },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname.startsWith(href.replace(/\/$/, ""));
}

function AgentBadge() {
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.get<AgentStatus>("/api/agent").then((a) => alive && setAgent(a)).catch(() => {});
    load();
    const id = setInterval(() => document.visibilityState === "visible" && load(), 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  if (!agent) return null;
  const running = agent.running;
  const busy = agent.control?.busy;
  return (
    <div className="flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-2"
      title={running ? `Agent PID ${agent.pid ?? "?"}, version ${agent.version ?? "?"}` : "Telegram agent is not running"}>
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: running ? "var(--good)" : "var(--ink-3)" }} />
      <span>SENTINAL AI: {running ? (busy ? "working" : "online") : "offline"}</span>
      {agent.control?.limits ? <span className="hidden text-ink-3 md:inline">· {agent.control.limits}</span> : null}
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [authed, setAuthed] = useState(false);
  const isLogin = pathname.startsWith("/login");

  useEffect(() => {
    if (isLogin) return;
    api.get("/api/session").then(() => setAuthed(true)).catch(() => {});
  }, [isLogin]);

  if (isLogin) return <>{children}</>;

  async function logout() {
    try {
      await api.post("/api/logout");
    } finally {
      router.replace("/login/");
    }
  }

  return (
    <div className="flex min-h-screen">
      <aside
        className={`no-print fixed inset-y-0 left-0 z-40 w-60 shrink-0 border-r border-line bg-surface transition-transform lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-16 items-center gap-2.5 border-b border-line px-5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent">
            <IconShield width={18} height={18} />
          </span>
          <div className="leading-tight">
            <div className="text-[13px] font-semibold tracking-wide">SENTINAL</div>
            <div className="text-[10px] font-medium tracking-[0.18em] text-ink-3">CONTROL CENTER</div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5 p-3" aria-label="Main">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link key={href} href={href} onClick={() => setOpen(false)}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${active ? "bg-accent/15 text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`}
                aria-current={active ? "page" : undefined}>
                <Icon className={active ? "text-accent" : "text-ink-3"} />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-line p-3">
          <div className="mb-2 px-3 text-[11px] leading-snug text-ink-3">
            Read-only · 127.0.0.1 only
          </div>
          <button onClick={logout}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink">
            <IconLogout className="text-ink-3" /> Sign out
          </button>
        </div>
      </aside>
      {open ? <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={() => setOpen(false)} /> : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-page/85 px-4 backdrop-blur md:px-8">
          <button className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 lg:hidden" onClick={() => setOpen(true)}
            aria-label="Open menu">
            <IconMenu />
          </button>
          <div className="hidden text-sm text-ink-3 sm:block lg:hidden">SENTINAL CONTROL CENTER</div>
          <div className="ml-auto flex items-center gap-3">{authed ? <AgentBadge /> : null}</div>
        </header>
        <main className="print-full mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8">
          {authed ? children : <div className="py-24 text-center text-sm text-ink-3">Checking session…</div>}
        </main>
      </div>
    </div>
  );
}
