"use client";

import Link from "next/link";
import { useState } from "react";
import { Card, ErrorBox, PageHeader, Tabs } from "@/components/ui";
import { Badge, DataTable, Kpi, SkeletonRows, type Col, type Tone } from "@/components/kit";
import { ago, dateTime } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Zone {
  id: string; symbol: string; source: string; detector: string; kind: string; tf: string; low: number; high: number; strength: number;
  note: string; status: string; dist_atr: number; price: number; first_seen: string; last_seen: string; watch: number;
}
interface Data {
  items: Zone[];
  summary: { total: number; active: number; symbols: number; by_detector: { detector: string; n: number; active: number }[] };
  universe: { binance: number; mt5: number; ts: string } | null;
  trade?: { today_opened?: number; target?: number; enabled?: boolean; why?: string; state?: string; candidates?: number; tried?: number; skipped?: string[]; ts?: string };
  recent?: { signal_id: string; symbol: string; direction: string; status: string; created_at: string; decision_note: string | null; approve: number | null; reason: string | null }[];
}

const KIND_TONE: Record<string, Tone> = { support: "good", demand: "good", "liq-low": "good", resistance: "bad", supply: "bad", "liq-high": "bad", range: "warn" };
const fmt = (n: number) => Number(n.toPrecision(6)).toString();

export default function ZonesPage() {
  usePageTitle("Zonalar");
  const [tab, setTab] = useState<"active" | "all">("active");
  const { data, error, loading } = useApi<Data>(`/api/desk/zones${tab === "active" ? "?status=active" : ""}`, 15000);

  const cols: Col<Zone>[] = [
    { key: "s", label: "Instrument", sort: (r) => r.symbol, render: (r) => <span><span className="font-semibold">{r.symbol}</span> <span className="text-[10px] text-ink-3">{r.source}</span></span> },
    { key: "d", label: "Xodim", sort: (r) => r.detector, className: "font-mono text-xs", render: (r) => r.detector },
    { key: "k", label: "Tur", sort: (r) => r.kind, render: (r) => <Badge tone={KIND_TONE[r.kind] ?? "mute"}>{r.kind}</Badge> },
    { key: "t", label: "TF", sort: (r) => r.tf, className: "text-xs", render: (r) => r.tf },
    { key: "z", label: "Zona", className: "tabular font-mono text-xs", render: (r) => `${fmt(r.low)} – ${fmt(r.high)}` },
    { key: "p", label: "Narx", className: "tabular font-mono text-xs", render: (r) => fmt(r.price) },
    { key: "di", label: "Masofa (ATR)", sort: (r) => r.dist_atr, className: "tabular text-xs", render: (r) => (r.dist_atr <= 0.001 ? "ichida" : r.dist_atr.toFixed(2)) },
    { key: "st", label: "Kuch", sort: (r) => r.strength, className: "tabular", render: (r) => r.strength },
    { key: "su", label: "Holat", sort: (r) => r.status, render: (r) => <span className="inline-flex gap-1"><Badge tone={r.status === "active" ? "good" : "mute"}>{r.status === "active" ? "AKTIV" : "kutilmoqda"}</Badge>{r.watch ? <Badge tone="info">kuzatuv</Badge> : null}</span> },
    { key: "n", label: "Izoh", className: "text-xs text-ink-3", render: (r) => r.note },
    { key: "l", label: "Yangilandi", sort: (r) => r.last_seen, className: "whitespace-nowrap text-xs text-ink-3", render: (r) => ago(r.last_seen) },
  ];

  return (
    <>
      <PageHeader title="Zonalar" subtitle="ZONE-1..5 butun bozorni (Binance USDT juftliklari va MT5 terminal simvollari) har 5 daqiqada skanerlaydi. Zonalar hisoblanadi, taxmin emas. Zonaning o'zi zdelka ochmaydi." />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Aktiv zonalar" value={data ? data.summary.active : "N/A"} sub="narx ichida yoki 0.5 ATR yaqinda" />
        <Kpi label="Jami zonalar" value={data ? data.summary.total : "N/A"} sub={data ? `${data.summary.symbols} instrumentda` : undefined} />
        <Kpi label="Oxirgi yangilanish" value={data?.universe ? ago(data.universe.ts) : "N/A"} sub="universe ro'yxati (soatiga 1 marta)" />
        <Kpi label="Skaner doirasi" value={data?.universe ? data.universe.binance + data.universe.mt5 : "N/A"} sub={data?.universe ? `Binance ${data.universe.binance} · MT5 ${data.universe.mt5}` : "skaner hali o'tmagan"} />
        <Kpi label="Bugungi zona zdelkalari (DIR-1)" value={data?.trade ? `${data.trade.today_opened ?? 0} / ${data.trade.target ?? 10}` : "N/A"}
          sub={data?.trade?.enabled === false ? `to'xtagan: ${data.trade.why ?? ""}` : "Toshkent kuni; maqsad — niyat, himoyalar o'zgarmaydi"} />
      </div>
      {data?.summary.by_detector.length ? (
        <div className="mb-4 flex flex-wrap gap-2 text-xs">{data.summary.by_detector.map((d) => <Badge key={d.detector} tone="info">{d.detector}: {d.n} zona, {d.active} aktiv</Badge>)}</div>
      ) : null}
      <Card title="DIR-1 zona vazifasi: nega zdelka ochildi / ochilmadi" subtitle={data?.trade?.ts ? `Oxirgi tekshiruv: ${dateTime(data.trade.ts)} (Toshkent) — ${data.trade.enabled === false ? `to'xtagan: ${data.trade.why ?? ""}` : data.trade.state ?? ""}` : "Hali tekshiruv bo'lmagan"} className="mb-4" bodyClass="p-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Oxirgi tekshiruv: nomzod {data?.trade?.candidates ?? "—"}, urinish {data?.trade?.tried ?? "—"}</div>
            {data?.trade?.skipped?.length ? <ul className="flex flex-col gap-1 text-xs text-ink-2">{data.trade.skipped.map((x, i) => <li key={i}>• {x}</li>)}</ul> : <div className="text-xs text-ink-3">Rad etilgan nomzod yo&apos;q (yoki hali tekshirilmagan).</div>}
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Oxirgi zona signallari</div>
            {!data?.recent?.length ? <div className="text-xs text-ink-3">Hali zona signali bo&apos;lmagan.</div> : (
              <ul className="flex flex-col gap-2 text-xs">{data.recent.map((r) => (
                <li key={r.signal_id} className="rounded-lg border border-line bg-surface-2 p-2">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{r.symbol}</span><Badge tone={r.direction === "LONG" ? "good" : "bad"}>{r.direction === "LONG" ? "BUY" : "SELL"}</Badge>
                    <Badge tone={r.status === "CONFIRMED" ? "good" : r.status === "REJECTED" || r.status === "INVALIDATED" ? "bad" : "mute"}>{r.status}</Badge>
                    <span className="ml-auto text-ink-3">{dateTime(r.created_at)}</span></div>
                  <div className="mt-1 text-ink-3">{r.approve === 0 ? `Bahs: rad — ${(r.reason ?? "").slice(0, 200)}` : r.approve === 1 ? `Bahs: ruxsat. ${r.decision_note ?? ""}` : r.decision_note ?? ""}</div>
                </li>))}</ul>
            )}
          </div>
        </div>
      </Card>
      <Card actions={<Tabs value={tab} onChange={setTab} items={[{ value: "active", label: "Aktiv" }, { value: "all", label: "Hammasi (400 gacha)" }]} />} bodyClass="p-0">
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : loading && !data ? <SkeletonRows rows={8} /> : (
          <DataTable rows={data?.items ?? []} cols={cols} rowKey={(r) => r.id} pageSize={30}
            search={(r) => `${r.symbol} ${r.detector} ${r.kind} ${r.tf}`}
            filters={[
              { label: "Xodim", options: ["ZONE-1", "ZONE-2", "ZONE-3", "ZONE-4", "ZONE-5"], pick: (r) => r.detector },
              { label: "Manba", options: ["binance", "mt5"], pick: (r) => r.source },
              { label: "Tur", options: Array.from(new Set((data?.items ?? []).map((r) => r.kind))), pick: (r) => r.kind },
            ]}
            empty="Hozircha zona yo'q. Agent qayta ishga tushgandan keyin birinchi skaner ~1-5 daqiqada tugaydi." />
        )}
      </Card>
      <p className="mt-3 text-xs text-ink-3">Zona ro&apos;yxati grafikda ham chiziladi: <Link href="/chart/" className="text-accent underline">Grafik</Link>. Muhokama chatda: <Link href="/desk/" className="text-accent underline">Trading bo&apos;limi</Link>.</p>
    </>
  );
}
