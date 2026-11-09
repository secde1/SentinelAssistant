"use client";

import Link from "next/link";
import { useState } from "react";
import { LineChart } from "@/components/charts";
import { IconBot, IconPulse, IconReport, IconTrend } from "@/components/icons";
import { Card, PageHeader, Tabs } from "@/components/ui";
import { Badge, Dot, Kpi, SideBadge, SkeletonRows, num, signTone } from "@/components/kit";
import { EXEC_TONE } from "@/lib/execStatus";
import { dateTime, timeOnly, ago } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Kpis { signals: number; open_positions: number; closed_n: number; win_rate: number | null; profit_factor: number | null; demo_net: number | null; paper_r: number | null; strategies: number }
interface Market { items: { symbol: string; note: string; price: number | null; change_pct: number | null }[]; error: string | null }
interface Sig { signal_id: string; created_at: string; symbol: string; direction: string; entry: number | null; sl: number | null; tp: number | null; status: string; tier: string | null; exec_status?: string }
interface Pos { open: { position_id: number; symbol: string; side: string; volume: number; price_open: number; profit: number }[]; closed: { position_id: number; symbol: string; direction: string; net: number | null; closed_at: string; reason: string | null }[] }
interface Member { id: string; title: string; unit: string; active: boolean; last_ts: string | null; task?: string | null }
interface Msg { id: number; ts: string; role: string; kind: string; text: string }

function price(p: number | null) {
  if (p === null) return "N/A";
  return p >= 1000 ? p.toLocaleString("en-US", { maximumFractionDigits: 2 }) : p.toFixed(4);
}

export default function DashboardPage() {
  usePageTitle("Dashboard");
  const kpi = useApi<{ kpi: Kpis | null }>("/api/desk/dashboard", 15000);
  const market = useApi<Market>("/api/desk/market", 15000);
  const sigs = useApi<{ items: Sig[] }>("/api/desk/signals", 15000);
  const pos = useApi<Pos>("/api/desk/positions", 10000);
  const staff = useApi<{ members: Member[] }>("/api/desk/staff", 5000);
  const msgs = useApi<{ items: Msg[] }>("/api/desk/messages", 5000);
  const [tab, setTab] = useState<"sig" | "open" | "closed">("sig");

  const k = kpi.data?.kpi ?? null;
  const closed = [...(pos.data?.closed ?? [])].reverse();
  const eq = closed.filter((c) => c.net !== null).reduce<{ t: string; v: number }[]>((acc, c) => {
    const prev = acc.length ? acc[acc.length - 1].v : 0;
    acc.push({ t: c.closed_at, v: Math.round((prev + (c.net as number)) * 100) / 100 });
    return acc;
  }, []);
  const members = staff.data?.members ?? [];
  const lastMsgs = (msgs.data?.items ?? []).slice(-6).reverse();

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Barcha raqamlar agent bazasidan olinadi. Ma'lumot bo'lmasa — N/A." />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi icon={<IconTrend width={16} height={16} />} label="Total Signals" value={k ? k.signals : "N/A"} sub="skaner topgan" />
        <Kpi icon={<IconPulse width={16} height={16} />} label="Active Positions" value={k ? k.open_positions : "N/A"} sub="MT5 DEMO, ochiq" />
        <Kpi label="Win Rate" value={k?.win_rate != null ? `${k.win_rate}%` : "N/A"} sub={k ? `${k.closed_n} ta yopilgan zdelka` : undefined} />
        <Kpi label="Profit Factor" value={num(k?.profit_factor)} sub="yopilgan DEMO zdelkalar" />
        <Kpi label="Total P/L (demo)" value={k?.demo_net != null ? `${k.demo_net > 0 ? "+" : ""}${k.demo_net}` : "N/A"} tone={k?.demo_net == null ? undefined : k.demo_net >= 0 ? "good" : "bad"} sub={k?.paper_r != null ? `paper: ${k.paper_r} R` : "paper natija yo'q"} />
        <Kpi icon={<IconReport width={16} height={16} />} label="Research Strategies" value={k ? k.strategies : "N/A"} sub="reestrdagi strategiyalar" />
      </div>
      {k && k.closed_n < 30 ? <p className="mb-4 text-xs text-warning">Namuna kichik ({k.closed_n} ta zdelka): Win Rate va Profit Factor ishonchli statistika emas.</p> : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-4 xl:col-span-2">
          <Card title="Market Overview" subtitle="Binance ochiq narxi; XAU/EUR/GBP — taxminiy proksi, MT5 narxi emas" bodyClass="p-0">
            {market.loading && !market.data ? <SkeletonRows rows={5} /> : (
              <>
                {market.data?.error ? <div className="px-5 pt-3 text-xs text-warning">{market.data.error}</div> : null}
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-3"><th className="px-5 py-2.5">Instrument</th><th className="px-3">Narx</th><th className="px-3">24s</th><th className="px-5 text-right">Manba</th></tr></thead>
                  <tbody>
                    {(market.data?.items ?? []).map((m) => (
                      <tr key={m.symbol} className="border-t border-line/50 hover:bg-surface-2">
                        <td className="px-5 py-2.5 font-semibold">{m.symbol}</td>
                        <td className="tabular px-3 font-mono">{price(m.price)}</td>
                        <td className={`tabular px-3 ${signTone(m.change_pct)}`}>{m.change_pct === null ? "N/A" : `${m.change_pct > 0 ? "+" : ""}${m.change_pct.toFixed(2)}%`}</td>
                        <td className="px-5 text-right text-xs text-ink-3">{m.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </Card>

          <Card title="Equity (yopilgan DEMO zdelkalar)" subtitle="Jamlangan sof natija; MT5 DEMO hisobi" >
            {eq.length < 2 ? <div className="py-10 text-center text-sm text-ink-3">Grafik uchun kamida 2 ta yopilgan zdelka kerak.</div> : (
              <LineChart ariaLabel="Equity" labels={eq.map((e) => e.t)} format={(v) => v.toFixed(2)}
                series={[{ name: "Jamlangan natija", color: "var(--accent)", values: eq.map((e) => e.v) }]} height={200} />
            )}
          </Card>

          <Card title="Trading Activity" actions={<Tabs value={tab} onChange={setTab} items={[{ value: "sig", label: "Signallar" }, { value: "open", label: "Ochiq" }, { value: "closed", label: "Yopilgan" }]} />} bodyClass="p-0">
            {sigs.loading && !sigs.data ? <SkeletonRows /> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  {tab === "sig" ? (
                    <>
                      <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-3"><th className="px-5 py-2.5">Vaqt</th><th>Symbol</th><th>Yo&apos;nalish</th><th>Kirish</th><th>SL</th><th>TP</th><th className="pr-5">Holat</th></tr></thead>
                      <tbody>{(sigs.data?.items ?? []).slice(0, 8).map((s) => (
                        <tr key={s.signal_id} className="border-t border-line/50 hover:bg-surface-2"><td className="px-5 py-2 text-xs text-ink-3">{timeOnly(s.created_at)}</td><td className="font-semibold">{s.symbol}</td><td><SideBadge side={s.direction} /></td>
                          <td className="tabular font-mono text-xs">{s.entry ?? "N/A"}</td><td className="tabular font-mono text-xs">{s.sl ?? "N/A"}</td><td className="tabular font-mono text-xs">{s.tp ?? "N/A"}</td><td className="pr-5"><Badge tone={EXEC_TONE[s.exec_status ?? ""] ?? "mute"}>{s.exec_status ?? s.status}</Badge></td></tr>))}</tbody>
                    </>
                  ) : tab === "open" ? (
                    <>
                      <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-3"><th className="px-5 py-2.5">Ticket</th><th>Symbol</th><th>Tomon</th><th>Hajm</th><th>Kirish</th><th className="pr-5">P/L</th></tr></thead>
                      <tbody>{(pos.data?.open ?? []).map((p) => (
                        <tr key={p.position_id} className="border-t border-line/50"><td className="px-5 py-2 font-mono text-xs">{p.position_id}</td><td className="font-semibold">{p.symbol}</td><td><SideBadge side={p.side} /></td><td className="tabular">{p.volume}</td><td className="tabular font-mono text-xs">{p.price_open}</td><td className={`tabular pr-5 font-semibold ${signTone(p.profit)}`}>{num(p.profit)}</td></tr>))}
                        {!pos.data?.open.length ? <tr><td colSpan={6} className="py-8 text-center text-ink-3">Ochiq pozitsiya yo&apos;q.</td></tr> : null}</tbody>
                    </>
                  ) : (
                    <>
                      <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-3"><th className="px-5 py-2.5">Yopilgan</th><th>Symbol</th><th>Tomon</th><th>Sabab</th><th className="pr-5">Natija</th></tr></thead>
                      <tbody>{(pos.data?.closed ?? []).slice(0, 8).map((c) => (
                        <tr key={c.position_id} className="border-t border-line/50"><td className="px-5 py-2 text-xs text-ink-3">{dateTime(c.closed_at)}</td><td className="font-semibold">{c.symbol}</td><td><SideBadge side={c.direction} /></td><td className="text-xs">{c.reason ?? "—"}</td><td className={`tabular pr-5 font-semibold ${signTone(c.net)}`}>{num(c.net)}</td></tr>))}
                        {!pos.data?.closed.length ? <tr><td colSpan={5} className="py-8 text-center text-ink-3">Yopilgan pozitsiya yo&apos;q.</td></tr> : null}</tbody>
                    </>
                  )}
                </table>
              </div>
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          <Card title="AI Agents" subtitle="Har xodim hozir/oxirgi nima ish qilgani (yozilgan ma'lumotdan)" actions={<Link href="/agents/" className="text-xs text-accent hover:underline">Hammasi →</Link>} bodyClass="p-2">
            {staff.loading && !staff.data ? <SkeletonRows rows={6} /> : members.map((m) => (
              <div key={m.id} className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-surface-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-3 text-ink-3"><IconBot width={16} height={16} /></span>
                <div className="min-w-0 flex-1"><div className="font-mono text-xs font-semibold">{m.id} <span className="font-sans font-normal text-ink-3">· {m.title}</span></div><div className="truncate text-[11px] text-ink-2" title={m.task ?? ""}>{m.task ?? "hali ish yo'q"}</div></div>
                <div className="flex items-center gap-1.5 text-[11px] text-ink-3"><Dot on={m.active ? true : null} pulse />{m.active ? "ishlayapti" : m.last_ts ? ago(m.last_ts) : "kutmoqda"}</div>
              </div>
            ))}
          </Card>
          <Card title="Oxirgi muhokamalar" actions={<Link href="/desk/" className="text-xs text-accent hover:underline">Ochish →</Link>} bodyClass="p-2">
            {!lastMsgs.length ? <div className="py-8 text-center text-sm text-ink-3">Hali muhokama bo&apos;lmagan.</div> : lastMsgs.map((m) => (
              <div key={m.id} className="rounded-lg px-3 py-2 hover:bg-surface-2">
                <div className="font-mono text-[11px] text-accent">{m.role} <span className="text-ink-3">· {ago(m.ts)}</span></div>
                <div className="mt-0.5 line-clamp-2 text-xs text-ink-2">{m.text}</div>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  );
}
