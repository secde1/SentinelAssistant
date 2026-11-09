"use client";

import { useState } from "react";
import { Card, ErrorBox, PageHeader, Tabs } from "@/components/ui";
import { Badge, DataTable, Drawer, Kpi, SideBadge, SkeletonRows, num, signTone, type Col } from "@/components/kit";
import { dateTime } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Open { position_id: number; symbol: string; side: string; volume: number; price_open: number; sl: number; tp: number; profit: number; swap: number; magic: number | null; opened_at: string; ts: string }
interface Group { signal_id: string; symbol: string; side: string; status: string; sl: number; risk_money: number; risk_actual: number; mode: string; opened_at: string; closed_at: string | null; note: string | null; tickets?: unknown; legs?: unknown }
interface Closed { position_id: number; symbol: string; direction: string; strategy: string | null; opened_at: string; closed_at: string; net: number | null; r_multiple: number | null; reason: string | null; source: string | null }
interface Paper { signal_id: string; symbol: string; direction: string; entry_type: string | null; entry_signal: number | null; sl: number | null; tp: number | null; confirmed_at: string; status: string; entry_price: number | null; exit_price: number | null; r_multiple: number | null; note: string | null }
interface Data { open: Open[]; groups: Group[]; closed: Closed[]; paper: Paper[]; counterfactual?: Paper[]; tests?: Paper[]; totals: { open_profit: number; closed_n: number; closed_net: number; wins: number; losses: number } }

type Sel = { kind: "open"; r: Open } | { kind: "closed"; r: Closed } | { kind: "group"; r: Group } | { kind: "paper"; r: Paper } | { kind: "cf"; r: Paper };

function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return <dl className="grid grid-cols-2 gap-3">{rows.map(([k, v]) => <div key={k} className="rounded-lg border border-line bg-surface-2 p-3"><dt className="text-[11px] text-ink-3">{k}</dt><dd className="mt-0.5 break-words font-mono text-sm">{v ?? "N/A"}</dd></div>)}</dl>;
}

export default function PositionsPage() {
  usePageTitle("Pozitsiyalar");
  const { data, error, loading } = useApi<Data>("/api/desk/positions", 5000);
  const ctrl = useApi<{ balance: { balance: number; ts: string } | null }>("/api/desk/control", 15000);
  const [tab, setTab] = useState<"open" | "closed" | "group" | "paper" | "cf" | "test">("open");
  const [sel, setSel] = useState<Sel | null>(null);

  const openCols: Col<Open>[] = [
    { key: "t", label: "Ticket", sort: (r) => r.position_id, className: "font-mono text-xs", render: (r) => r.position_id },
    { key: "s", label: "Symbol", sort: (r) => r.symbol, render: (r) => <span className="font-semibold">{r.symbol}</span> },
    { key: "d", label: "Direction", sort: (r) => r.side, render: (r) => <SideBadge side={r.side} /> },
    { key: "v", label: "Volume", sort: (r) => r.volume, className: "tabular", render: (r) => r.volume },
    { key: "e", label: "Entry", sort: (r) => r.price_open, className: "tabular font-mono text-xs", render: (r) => r.price_open },
    { key: "c", label: "Current", className: "text-xs text-ink-3", render: () => "N/A" },
    { key: "sl", label: "SL", sort: (r) => r.sl, className: "tabular font-mono text-xs", render: (r) => r.sl || "N/A" },
    { key: "tp", label: "TP", sort: (r) => r.tp, className: "tabular font-mono text-xs", render: (r) => r.tp || "N/A" },
    { key: "p", label: "Floating P/L", sort: (r) => r.profit, className: "tabular font-semibold", render: (r) => <span className={signTone(r.profit)}>{num(r.profit)}</span> },
    { key: "st", label: "Status", render: () => <Badge tone="good">OPEN</Badge> },
  ];
  const closedCols: Col<Closed>[] = [
    { key: "t", label: "Ticket", sort: (r) => r.position_id, className: "font-mono text-xs", render: (r) => r.position_id },
    { key: "s", label: "Symbol", sort: (r) => r.symbol, render: (r) => <span className="font-semibold">{r.symbol}</span> },
    { key: "d", label: "Direction", sort: (r) => r.direction, render: (r) => <SideBadge side={r.direction} /> },
    { key: "n", label: "Net P/L", sort: (r) => r.net, className: "tabular font-semibold", render: (r) => <span className={signTone(r.net)}>{num(r.net)}</span> },
    { key: "r", label: "R", sort: (r) => r.r_multiple, className: "tabular", render: (r) => num(r.r_multiple) },
    { key: "re", label: "Sabab", sort: (r) => r.reason, className: "text-xs", render: (r) => r.reason ?? "N/A" },
    { key: "c", label: "Yopilgan", sort: (r) => r.closed_at, className: "whitespace-nowrap text-xs text-ink-3", render: (r) => dateTime(r.closed_at) },
  ];
  const groupCols: Col<Group>[] = [
    { key: "id", label: "Signal", sort: (r) => r.signal_id, className: "font-mono text-xs", render: (r) => r.signal_id },
    { key: "s", label: "Symbol", sort: (r) => r.symbol, render: (r) => <span className="font-semibold">{r.symbol}</span> },
    { key: "d", label: "Direction", render: (r) => <SideBadge side={r.side} /> },
    { key: "m", label: "Rejim", sort: (r) => r.mode, className: "text-xs", render: (r) => r.mode },
    { key: "st", label: "Holat", sort: (r) => r.status, render: (r) => <Badge tone={r.status === "OPEN" ? "good" : "mute"}>{r.status}</Badge> },
    { key: "rk", label: "Risk reja / haqiqiy", className: "tabular text-xs", render: (r) => `${num(r.risk_money)} / ${num(r.risk_actual)}` },
    { key: "o", label: "Ochilgan", sort: (r) => r.opened_at, className: "whitespace-nowrap text-xs text-ink-3", render: (r) => dateTime(r.opened_at) },
  ];
  const paperCols: Col<Paper>[] = [
    { key: "id", label: "Signal", sort: (r) => r.signal_id, className: "font-mono text-xs", render: (r) => r.signal_id },
    { key: "s", label: "Symbol", sort: (r) => r.symbol, render: (r) => <span className="font-semibold">{r.symbol}</span> },
    { key: "d", label: "Direction", render: (r) => <SideBadge side={r.direction} /> },
    { key: "e", label: "Entry", className: "tabular font-mono text-xs", render: (r) => r.entry_price ?? r.entry_signal ?? "N/A" },
    { key: "sl", label: "SL / TP", className: "tabular font-mono text-xs", render: (r) => `${r.sl ?? "N/A"} / ${r.tp ?? "N/A"}` },
    { key: "r", label: "R", sort: (r) => r.r_multiple, className: "tabular", render: (r) => num(r.r_multiple) },
    { key: "st", label: "Holat", sort: (r) => r.status, render: (r) => <Badge tone="warn">{r.status}</Badge> },
    { key: "c", label: "Tasdiqlangan", sort: (r) => r.confirmed_at, className: "whitespace-nowrap text-xs text-ink-3", render: (r) => dateTime(r.confirmed_at) },
  ];

  const t = data?.totals;
  return (
    <>
      <PageHeader title="Pozitsiyalar" subtitle="Real MT5 (DEMO hisob) va Paper (simulyatsiya) alohida ko'rsatiladi — aralashtirilmaydi." />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Balans (MT5 demo)" value={ctrl.data?.balance ? num(ctrl.data.balance.balance) : "N/A"} sub={ctrl.data?.balance ? dateTime(ctrl.data.balance.ts) : "monitor hali yozmagan"} />
        <Kpi label="Ochiq floating P/L" value={t ? num(t.open_profit) : "N/A"} tone={t ? (t.open_profit >= 0 ? "good" : "bad") : undefined} sub={data ? `${data.open.length} ochiq` : undefined} />
        <Kpi label="Yopilgan sof natija" value={t ? num(t.closed_net) : "N/A"} tone={t ? (t.closed_net >= 0 ? "good" : "bad") : undefined} sub={t ? `${t.closed_n} ta zdelka` : undefined} />
        <Kpi label="Foyda / Zarar" value={t ? `${t.wins} / ${t.losses}` : "N/A"} sub="yopilgan DEMO pozitsiyalar" />
      </div>
      <Drawer open={!!sel} onClose={() => setSel(null)} title={sel ? ("position_id" in sel.r ? `Ticket ${sel.r.position_id}` : sel.r.signal_id) : ""} subtitle={sel ? (sel.kind === "paper" ? "PAPER (ijro qilinadigan simulyatsiya)" : sel.kind === "cf" ? "COUNTERFACTUAL (rad etilgan signal — statistikaga kirmaydi)" : "MT5 DEMO") : ""}>
        {sel?.kind === "open" ? <KV rows={[["Symbol", sel.r.symbol], ["Tomon", sel.r.side], ["Hajm", sel.r.volume], ["Kirish", sel.r.price_open], ["SL", sel.r.sl || null], ["TP", sel.r.tp || null], ["Floating P/L", num(sel.r.profit)], ["Swap", num(sel.r.swap)], ["Magic", sel.r.magic], ["Ochilgan", dateTime(sel.r.opened_at)], ["Monitor yozuvi", dateTime(sel.r.ts)]]} /> : null}
        {sel?.kind === "closed" ? <KV rows={[["Symbol", sel.r.symbol], ["Tomon", sel.r.direction], ["Strategiya", sel.r.strategy], ["Net", num(sel.r.net)], ["R", num(sel.r.r_multiple)], ["Sabab", sel.r.reason], ["Manba", sel.r.source], ["Ochilgan", dateTime(sel.r.opened_at)], ["Yopilgan", dateTime(sel.r.closed_at)]]} /> : null}
        {sel?.kind === "group" ? <div className="flex flex-col gap-3"><KV rows={[["Symbol", sel.r.symbol], ["Tomon", sel.r.side], ["Holat", sel.r.status], ["Rejim", sel.r.mode], ["SL", sel.r.sl], ["Risk (reja)", num(sel.r.risk_money)], ["Risk (haqiqiy)", num(sel.r.risk_actual)], ["Ochilgan", dateTime(sel.r.opened_at)]]} />{sel.r.note ? <p className="text-sm text-ink-2">{sel.r.note}</p> : null}<pre className="overflow-x-auto rounded-lg border border-line bg-surface-2 p-3 text-[11px] text-ink-3">{JSON.stringify({ tickets: sel.r.tickets, legs: sel.r.legs }, null, 2)}</pre></div> : null}
        {sel?.kind === "paper" || sel?.kind === "cf" ? <KV rows={[["Symbol", sel.r.symbol], ["Tomon", sel.r.direction], ["Kirish turi", sel.r.entry_type], ["Signal narxi", sel.r.entry_signal], ["Kirish narxi", sel.r.entry_price], ["SL", sel.r.sl], ["TP", sel.r.tp], ["Chiqish narxi", sel.r.exit_price], ["R", num(sel.r.r_multiple)], ["Holat", sel.r.status], ["Izoh", sel.r.note]]} /> : null}
      </Drawer>
      <Card actions={<Tabs value={tab} onChange={setTab} items={[
        { value: "open", label: "Ochiq (MT5)", count: data?.open.length }, { value: "closed", label: "Yopilgan (MT5)", count: data?.closed.length },
        { value: "group", label: "Zdelka guruhlari", count: data?.groups.length }, { value: "paper", label: "Paper (ijro)", count: data?.paper.length },
        { value: "cf", label: "Counterfactual", count: data?.counterfactual?.length }, { value: "test", label: "Sinov (TEST)", count: data?.tests?.length }]} />} bodyClass="p-0">
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : loading && !data ? <SkeletonRows rows={6} /> : !data ? null : (
          tab === "open" ? <DataTable rows={data.open} cols={openCols} rowKey={(r) => String(r.position_id)} onRow={(r) => setSel({ kind: "open", r })} search={(r) => `${r.position_id} ${r.symbol}`} empty="Ochiq pozitsiya yo'q." />
          : tab === "closed" ? <DataTable rows={data.closed} cols={closedCols} rowKey={(r) => String(r.position_id)} onRow={(r) => setSel({ kind: "closed", r })} search={(r) => `${r.position_id} ${r.symbol} ${r.reason ?? ""}`} filters={[{ label: "Symbol", options: Array.from(new Set(data.closed.map((c) => c.symbol))), pick: (r) => r.symbol }]} empty="Yopilgan pozitsiya yo'q." />
          : tab === "group" ? <DataTable rows={data.groups} cols={groupCols} rowKey={(r) => r.signal_id} onRow={(r) => setSel({ kind: "group", r })} search={(r) => `${r.signal_id} ${r.symbol}`} empty="Hali guruh ochilmagan." />
          : tab === "cf" ? <DataTable rows={data.counterfactual ?? []} cols={paperCols} rowKey={(r) => r.signal_id} onRow={(r) => setSel({ kind: "cf", r })} search={(r) => `${r.signal_id} ${r.symbol}`} empty="Rad etilgan signal kuzatuvi yo'q." />
          : tab === "test" ? <DataTable rows={data.tests ?? []} cols={paperCols} rowKey={(r) => r.signal_id} onRow={(r) => setSel({ kind: "paper", r })} search={(r) => `${r.signal_id} ${r.symbol}`} empty="Sinov yozuvi yo'q." />
          : <DataTable rows={data.paper} cols={paperCols} rowKey={(r) => r.signal_id} onRow={(r) => setSel({ kind: "paper", r })} search={(r) => `${r.signal_id} ${r.symbol}`} empty="Paper pozitsiya yo'q." />
        )}
      </Card>
      <p className="mt-3 text-[11px] text-ink-3">Paper (ijro), Counterfactual (rad etilgan), Sinov va MT5 DEMO ijrolari alohida to&apos;plamlar — hech qachon aralashtirilmaydi. Joriy narx (Current) monitor bazasida saqlanmaydi, shuning uchun N/A. Floating P/L MT5&apos;dan olinadi.</p>
    </>
  );
}
