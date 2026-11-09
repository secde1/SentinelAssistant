"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ColorType, CrosshairMode, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import InstrumentPicker, { type Instrument, type Selected, type SourceInfo } from "@/components/InstrumentPicker";
import { Badge, Skeleton } from "@/components/kit";
import { ErrorBox, Tabs } from "@/components/ui";
import { ChartLayer, mergeZones, ZONE_CLASSES, type Hit, type Level, type RawLevel, type RawZone, type ZoneClass } from "@/lib/chartLayer";
import { tkAxis, tkFull } from "@/lib/format";
import { useApi, usePageTitle, usePersisted } from "@/lib/hooks";

interface ChartData { symbol: string; tf: string; market: string; source: string; candles: { time: number; open: number; high: number; low: number; close: number }[]; levels: RawLevel[]; zones: RawZone[]; error: string | null }
interface Instruments { items: Instrument[]; sources: Record<string, SourceInfo>; ts: string }
type TF = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d";
const TFS: TF[] = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const NEAREST = 12;

const css = (n: string, fb: string) => { try { return getComputedStyle(document.documentElement).getPropertyValue(n).trim() || fb; } catch { return fb; } };
const DEF_SEL: Selected = { market: "spot", symbol: "BTCUSDT" };
const NO_HIDDEN: ZoneClass[] = [];
interface Tip { hit: Hit; left: number; top: number }

export default function ChartPage() {
  usePageTitle("Grafik");
  const [sel, setSel] = usePersisted<Selected>("sx-chart-sel", DEF_SEL);
  const [tf, setTf] = usePersisted<TF>("sx-chart-tf", "1h");
  const [hidden, setHidden] = usePersisted<ZoneClass[]>("sx-chart-hidden", NO_HIDDEN);
  const [showLevels, setShowLevels] = useState(true);
  const [showPos, setShowPos] = useState(true);
  const [allZones, setAllZones] = useState(false);
  const [tip, setTip] = useState<Tip | null>(null);

  const inst = useApi<Instruments>("/api/desk/instruments", 600000);
  const { data, error, loading } = useApi<ChartData>(`/api/desk/chart?symbol=${encodeURIComponent(sel.symbol)}&tf=${tf}&market=${sel.market}`, 15000);

  const box = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const layer = useRef<ChartLayer>(new ChartLayer());
  const lastKey = useRef("");

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true, crosshair: { mode: CrosshairMode.Normal },
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--ink-2", "#aab5c4"), attributionLogo: true },
      grid: { vertLines: { color: css("--grid", "#1e2632") }, horzLines: { color: css("--grid", "#1e2632") } },
      rightPriceScale: { borderColor: css("--axis", "#2b3544"), scaleMargins: { top: 0.08, bottom: 0.08 } },
      localization: { timeFormatter: (t: number) => tkFull(t) },  // crosshair vaqti: Toshkent
      timeScale: {
        borderColor: css("--axis", "#2b3544"), timeVisible: true, rightOffset: 6,
        tickMarkFormatter: (t: number, type: number) => tkAxis(t, type < 3),  // 0-2: yil/oy/kun -> sana; 3+: vaqt (Toshkent)
      },
    });
    const series = chart.addCandlestickSeries({
      upColor: css("--good", "#19c37d"), downColor: css("--critical", "#f0524f"), borderVisible: false,
      wickUpColor: css("--good", "#19c37d"), wickDownColor: css("--critical", "#f0524f"), priceLineVisible: true, lastValueVisible: true,
    });
    series.attachPrimitive(layer.current);
    chartRef.current = chart;
    seriesRef.current = series;
    chart.subscribeCrosshairMove((p) => {
      if (!p.point || !wrap.current) { setTip(null); layer.current.setHover(null); return; }
      layer.current.setHover(layer.current.hoverId(p.point.x, p.point.y));
      const hit = layer.current.probe(p.point.x, p.point.y);
      const W = wrap.current.clientWidth, H = wrap.current.clientHeight, tw = 250, th = 120;  // tooltip konteynerdan chiqmaydi
      setTip(hit ? { hit, left: Math.max(6, Math.min(W - tw - 70, p.point.x + 14)), top: Math.max(6, Math.min(H - th - 6, p.point.y + 14)) } : null);
    });
    const l = layer.current;
    return () => { chart.remove(); chartRef.current = null; seriesRef.current = null; l.setHover(null); };
  }, []);

  const lastPrice = data?.candles.length ? data.candles[data.candles.length - 1].close : null;
  const merged = useMemo(() => mergeZones(data?.zones ?? []), [data?.zones]);
  const visibleZones = useMemo(() => {
    const z = merged.filter((x) => !hidden.includes(x.cls));
    if (allZones || lastPrice === null) return z;
    const dist = (x: { low: number; high: number }) => (lastPrice >= x.low && lastPrice <= x.high ? 0 : Math.min(Math.abs(lastPrice - x.low), Math.abs(lastPrice - x.high)));
    return [...z].sort((a, b) => dist(a) - dist(b)).slice(0, NEAREST);
  }, [merged, hidden, allZones, lastPrice]);
  const levels: Level[] = useMemo(() => (data?.levels ?? []).map((l, i) => ({
    id: `${l.kind}-${l.signal_id ?? "pos"}-${i}`, kind: (["entry", "sl", "tp", "position"].includes(l.kind) ? l.kind : "entry") as Level["kind"], price: l.price,
    text: l.kind === "position" ? l.label.replace(/^POS /, "POS ") : l.label, side: l.side,
  })), [data?.levels]);

  useEffect(() => {
    const series = seriesRef.current, chart = chartRef.current;
    if (!series || !chart || !data) return;
    const byTime = new Map<number, ChartData["candles"][number]>();
    for (const c of data.candles) byTime.set(c.time, c);  // takroriy vaqtlarsiz, o'sish tartibida
    const clean = Array.from(byTime.values()).sort((a, b) => a.time - b.time);
    const ref = clean.length ? clean[clean.length - 1].close : 1;  // narx aniqligi instrumentga qarab (EURUSD 5, JPY 3, BTC 2, mayda kripto 8)
    const precision = ref >= 1000 ? 2 : ref >= 100 ? 3 : ref >= 10 ? 4 : ref >= 1 ? 5 : ref >= 0.1 ? 6 : 8;
    series.applyOptions({ priceFormat: { type: "price", precision, minMove: Number((10 ** -precision).toFixed(precision)) } });
    series.setData(clean.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    const key = `${data.market}|${data.symbol}|${data.tf}`;
    if (key !== lastKey.current && clean.length) {  // faqat instrument/TF o'zgarganda: oxirgi ~150 sham (hammasi sig'dirilsa shamlar sirqiladi)
      lastKey.current = key;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, clean.length - 150), to: clean.length + 6 });
    }
  }, [data]);

  useEffect(() => {
    layer.current.setOptions({ zones: visibleZones, levels, hidden: new Set(hidden), showLevels, showPositions: showPos, lastPrice });
  }, [visibleZones, levels, hidden, showLevels, showPos, lastPrice]);

  function toggleClass(c: ZoneClass) {
    const next = hidden.includes(c) ? hidden.filter((x) => x !== c) : [...hidden, c];
    setHidden(next);
  }
  const counts = useMemo(() => Object.fromEntries(ZONE_CLASSES.map((c) => [c.id, merged.filter((z) => z.cls === c.id).length])), [merged]);

  return (
    <div className="flex h-[calc(100vh-7.5rem)] min-h-[520px] flex-col gap-3">
      <div className="shrink-0">
        <h1 className="text-2xl font-semibold tracking-tight">Grafik</h1>
        <p className="mt-1 max-w-4xl text-sm text-ink-3">Butun bozor: Binance Spot, MT5 (forex, metall, indeks, aksiya, xom ashyo, kripto). Zonalar, signal darajalari va pozitsiyalarni agent o&apos;zi bazaga yozadi — bu yerda avtomatik chiziladi; yo&apos;q bo&apos;lsa chizilmaydi.</p>
      </div>

      <div className="relative z-20 flex shrink-0 flex-wrap items-center gap-3">
        <InstrumentPicker items={inst.data?.items ?? []} sources={inst.data?.sources ?? {}} value={sel} loading={inst.loading} error={inst.error}
          onChange={setSel} />
        <Tabs value={tf} onChange={setTf} items={TFS.map((t) => ({ value: t, label: t }))} />
        <div className="ml-auto flex flex-wrap items-center gap-1.5 text-xs">
          {ZONE_CLASSES.map((c) => (
            <button key={c.id} onClick={() => toggleClass(c.id)} aria-pressed={!hidden.includes(c.id)} title={`${c.label} zonalarini ${hidden.includes(c.id) ? "ko'rsatish" : "yashirish"}`}
              className={`rounded-full border px-2.5 py-1 transition-colors ${hidden.includes(c.id) ? "border-line text-ink-3 line-through" : "border-accent/50 bg-accent/10 text-ink"}`}>
              {c.label} <span className="text-ink-3">{counts[c.id] ?? 0}</span>
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-line" />
          <button onClick={() => setShowLevels(!showLevels)} aria-pressed={showLevels} className={`rounded-full border px-2.5 py-1 ${showLevels ? "border-accent/50 bg-accent/10 text-ink" : "border-line text-ink-3 line-through"}`}>Entry/SL/TP</button>
          <button onClick={() => setShowPos(!showPos)} aria-pressed={showPos} className={`rounded-full border px-2.5 py-1 ${showPos ? "border-accent/50 bg-accent/10 text-ink" : "border-line text-ink-3 line-through"}`}>Pozitsiyalar</button>
          <button onClick={() => setAllZones(!allZones)} aria-pressed={allZones} title="Standart: narxga eng yaqin 12 ta zona" className={`rounded-full border px-2.5 py-1 ${allZones ? "border-accent/50 bg-accent/10 text-ink" : "border-line text-ink-3"}`}>{allZones ? "Hamma zonalar" : `Yaqin ${NEAREST} ta`}</button>
        </div>
      </div>

      {error ? <ErrorBox error={error} /> : null}
      {data?.error ? <ErrorBox error={data.error} /> : null}

      <div ref={wrap} className="relative isolate min-h-0 flex-1 overflow-hidden rounded-xl border border-line bg-surface">
        {loading && !data ? <div className="absolute inset-0 z-10 p-4"><Skeleton className="h-full w-full" /></div> : null}
        <div ref={box} className="absolute inset-0" />
        {tip ? (
          <div className="pointer-events-none absolute z-10 rounded-lg border border-line bg-surface-2/95 px-3 py-2 text-xs shadow-xl" style={{ left: tip.left, top: tip.top, width: 250 }} role="tooltip">
            <div className="mb-1 font-semibold">{tip.hit.title}</div>
            {tip.hit.lines.map((l, i) => <div key={i} className="text-ink-2">{l}</div>)}
          </div>
        ) : null}
        <div className="pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-2 text-xs">
          <span className="rounded-md bg-surface/80 px-2 py-1 font-semibold">{sel.symbol}</span>
          <Badge tone={sel.market === "mt5" ? "warn" : "info"}>{sel.market}</Badge>
          {lastPrice !== null ? <span className="tabular rounded-md bg-surface/80 px-2 py-1 font-mono">{Number(lastPrice.toPrecision(7))}</span> : null}
        </div>
      </div>
      {data && !data.levels.length ? <p className="shrink-0 text-xs text-ink-3">Bu instrument bo&apos;yicha signal yoki ochiq pozitsiya yo&apos;q — Entry/SL/TP chizilmaydi.{!merged.length ? " Zona ham topilmagan." : ""}</p> : null}
    </div>
  );
}
