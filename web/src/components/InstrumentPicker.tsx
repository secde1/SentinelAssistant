"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePersisted } from "@/lib/hooks";
import { IconChevron, IconSearch } from "./icons";
import { Badge, Skeleton } from "./kit";

export interface Instrument { symbol: string; market: "spot" | "futures-usdm" | "futures-coinm" | "mt5"; category: string; base?: string | null; quote?: string | null; tradable?: boolean; zones: number }
export interface SourceInfo { ok: boolean; count: number; error: string | null }
export interface Selected { market: Instrument["market"]; symbol: string }

const MARKET_LABEL: Record<string, string> = { spot: "Spot", "futures-usdm": "Futures USDT-M", "futures-coinm": "Futures COIN-M", mt5: "MT5" };
const TABS: { id: string; label: string; test: (i: Instrument, fav: Set<string>) => boolean }[] = [
  { id: "all", label: "Hammasi", test: () => true },
  { id: "fav", label: "★ Sevimli", test: (i, f) => f.has(key(i)) },
  { id: "zones", label: "Zonali", test: (i) => i.zones > 0 },
  { id: "spot", label: "Binance Spot", test: (i) => i.market === "spot" },
  { id: "fut", label: "Futures", test: (i) => i.market.startsWith("futures") },
  { id: "Forex", label: "Forex", test: (i) => i.market === "mt5" && i.category === "Forex" },
  { id: "Metals", label: "Metallar", test: (i) => i.market === "mt5" && i.category === "Metals" },
  { id: "Indices", label: "Indekslar", test: (i) => i.market === "mt5" && i.category === "Indices" },
  { id: "Stocks", label: "Aksiyalar", test: (i) => i.market === "mt5" && i.category === "Stocks" },
  { id: "Commodities", label: "Xom ashyo", test: (i) => i.market === "mt5" && i.category === "Commodities" },
  { id: "mcrypto", label: "Kripto (MT5)", test: (i) => i.market === "mt5" && i.category === "Crypto" },
  { id: "Indicators", label: "Indikatorlar", test: (i) => i.market === "mt5" && i.category === "Indicators" },
];
const key = (i: { market: string; symbol: string }) => `${i.market}:${i.symbol}`;
const LIMIT = 150;

const NO_FAV: string[] = [];

export default function InstrumentPicker({ items, sources, value, onChange, loading, error }: {
  items: Instrument[]; sources: Record<string, SourceInfo>; value: Selected; onChange: (s: Selected) => void; loading: boolean; error: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ0] = useState("");
  const [tab, setTab0] = useState("all");
  const [cursor, setCursor] = useState(0);
  const [favList, setFavList] = usePersisted<string[]>("sx-fav", NO_FAV);
  const fav = useMemo(() => new Set(favList), [favList]);
  const setQ = (v: string) => { setQ0(v); setCursor(0); };
  const setTab = (v: string) => { setTab0(v); setCursor(0); };
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 0); }, [open]);

  const counts = useMemo(() => Object.fromEntries(TABS.map((t) => [t.id, items.filter((i) => t.test(i, fav)).length])), [items, fav]);

  const rows = useMemo(() => {
    const t = TABS.find((x) => x.id === tab) ?? TABS[0];
    const n = q.trim().toLowerCase();
    let r = items.filter((i) => t.test(i, fav));
    if (n) r = r.filter((i) => i.symbol.toLowerCase().includes(n) || (i.base ?? "").toLowerCase() === n);
    const score = (i: Instrument) => (n && i.symbol.toLowerCase() === n ? 0 : n && i.symbol.toLowerCase().startsWith(n) ? 1 : 2) * 10 + (fav.has(key(i)) ? 0 : 5);
    r = [...r].sort((a, b) => score(a) - score(b) || b.zones - a.zones || a.symbol.localeCompare(b.symbol));
    return r;
  }, [items, tab, q, fav]);
  const shown = rows.slice(0, LIMIT);

  function toggleFav(i: Instrument, e: React.MouseEvent) {
    e.stopPropagation();
    const next = new Set(fav);
    if (next.has(key(i))) next.delete(key(i)); else next.add(key(i));
    setFavList(Array.from(next));
  }
  function choose(i: Instrument) {
    onChange({ market: i.market, symbol: i.symbol });
    setOpen(false);
    setQ("");
  }
  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") { setOpen(false); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(shown.length - 1, c + 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
    if (e.key === "Enter" && shown[cursor]) { e.preventDefault(); choose(shown[cursor]); }
  }
  useEffect(() => { (listRef.current?.querySelector(`[data-i="${cursor}"]`) as HTMLElement | null)?.scrollIntoView({ block: "nearest" }); }, [cursor]);

  const futuresDown = sources["futures-usdm"] && !sources["futures-usdm"].ok && sources["futures-coinm"] && !sources["futures-coinm"].ok;

  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}
        className="flex min-w-[220px] items-center justify-between gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2 text-left text-sm hover:border-accent/50">
        <span className="flex items-center gap-2"><span className="font-semibold">{value.symbol}</span><Badge tone="info">{MARKET_LABEL[value.market]}</Badge></span>
        <IconChevron className={`transition-transform ${open ? "-rotate-90" : "rotate-90"}`} width={14} height={14} />
      </button>
      {open ? (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-40 mt-2 flex max-h-[min(72vh,640px)] w-[min(680px,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl" onKeyDown={onKey}>
            <div className="flex items-center gap-2 border-b border-line px-3 py-2.5">
              <IconSearch width={16} height={16} className="text-ink-3" />
              <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Qidirish: ${items.length.toLocaleString("en-US")} ta instrument (BTC, EURUSD, AAPL, XAU…)`}
                aria-label="Instrument qidirish" spellCheck={false} className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-3" />
              {q ? <button onClick={() => setQ("")} className="text-xs text-ink-3 hover:text-ink">tozalash</button> : null}
            </div>
            <div className="flex flex-wrap gap-1.5 border-b border-line px-3 py-2">
              {TABS.filter((t) => counts[t.id] > 0 || t.id === "all" || t.id === "fut").map((t) => (
                <button key={t.id} onClick={() => setTab(t.id)} disabled={t.id === "fut" && futuresDown && !counts.fut}
                  title={t.id === "fut" && futuresDown ? "Binance Futures manbasi ulanmagan" : undefined}
                  className={`rounded-full border px-2.5 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${tab === t.id ? "border-accent bg-accent/15 text-ink" : "border-line text-ink-3 hover:text-ink"}`}>
                  {t.label} <span className="text-ink-3">{counts[t.id]}</span>
                </button>
              ))}
            </div>
            <div ref={listRef} role="listbox" className="min-h-[160px] flex-1 overflow-y-auto">
              {loading && !items.length ? <div className="flex flex-col gap-2 p-3">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div> : null}
              {error ? <div className="p-4 text-sm text-critical">Ro&apos;yxat olinmadi: {error}</div> : null}
              {!loading && !error && !shown.length ? <div className="p-6 text-center text-sm text-ink-3">Hech narsa topilmadi.</div> : null}
              {shown.map((i, idx) => (
                <div key={key(i)} data-i={idx} role="option" aria-selected={value.symbol === i.symbol && value.market === i.market} onClick={() => choose(i)} onMouseEnter={() => setCursor(idx)}
                  className={`flex cursor-pointer items-center gap-3 border-b border-line/40 px-3 py-2 text-sm ${idx === cursor ? "bg-surface-2" : ""} ${value.symbol === i.symbol && value.market === i.market ? "border-l-2 border-l-accent" : ""}`}>
                  <button onClick={(e) => toggleFav(i, e)} aria-label="Sevimli" className={fav.has(key(i)) ? "text-warning" : "text-ink-3 hover:text-warning"}>{fav.has(key(i)) ? "★" : "☆"}</button>
                  <span className="min-w-[110px] font-semibold">{i.symbol}</span>
                  <Badge tone={i.market === "mt5" ? "warn" : "info"}>{MARKET_LABEL[i.market]}</Badge>
                  <span className="text-xs text-ink-3">{i.market === "mt5" ? i.category : `${i.base ?? ""}/${i.quote ?? ""}`}</span>
                  <span className="ml-auto flex items-center gap-1.5">
                    {i.tradable ? <Badge tone="good">DEMO savdo</Badge> : null}
                    {i.zones > 0 ? <Badge tone="good">{i.zones} aktiv zona</Badge> : null}
                  </span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-2 text-[11px] text-ink-3">
              <span>{rows.length.toLocaleString("en-US")} topildi{rows.length > LIMIT ? ` (dastlabki ${LIMIT} ta — qidiruvni aniqlang)` : ""}</span>
              {Object.entries(sources).map(([k, s]) => (
                <span key={k} className={s.ok ? "" : "text-warning"} title={s.error ?? ""}>{k}: {s.ok ? `${s.count} ta` : "ulanmagan"}</span>
              ))}
              <span className="ml-auto">↑↓ tanlash · Enter ochish · Esc yopish</span>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
