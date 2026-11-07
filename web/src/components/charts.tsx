"use client";

// Kichik SVG grafiklar (tashqi kutubxonasiz). Qoidalar: ingichka belgilar, 2px chiziq, bitta o'q, hover tooltip,
// matn rangi — matn tokenlari (seriya rangi faqat belgida), 2+ seriyada legenda.
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    setWidth(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * p;
}

export function Legend({ items }: { items: { name: string; color: string; value?: ReactNode; marker?: "line" | "box" }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-2">
      {items.map((it) => (
        <span key={it.name} className="inline-flex items-center gap-1.5">
          {it.marker === "line" ? (
            <span className="inline-block h-0.5 w-3.5 rounded" style={{ background: it.color }} />
          ) : (
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: it.color }} />
          )}
          {it.name}
          {it.value !== undefined ? <span className="tabular text-ink-3">{it.value}</span> : null}
        </span>
      ))}
    </div>
  );
}

export interface LineSeries {
  name: string;
  color: string;
  values: (number | null)[];
}

export function LineChart({ series, labels, yMax, format, height = 220, ariaLabel }: {
  series: LineSeries[]; labels: string[]; yMax?: number; format: (v: number) => string; height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  const [min, max] = useMemo(() => {
    const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
    const lo = Math.min(0, ...all);  // manfiy qiymat (masalan jamlangan R) qirqilmaydi
    const hi = yMax ?? niceMax(Math.max(1, ...all) * 1.1);
    return [lo < 0 ? -niceMax(-lo * 1.1) : 0, hi];
  }, [series, yMax]);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => min + f * (max - min));
  // Chap chekka eng uzun o'q yozuviga qarab — "1.5 MB/s" kabi yozuvlar kesilmasin.
  const pad = { l: Math.max(36, Math.max(...ticks.map((t) => format(t).length)) * 6.8 + 14), r: 16, t: 12, b: 24 };
  const w = Math.max(0, width - pad.l - pad.r);
  const h = height - pad.t - pad.b;
  const x = (i: number) => pad.l + (n <= 1 ? w : (i / (n - 1)) * w);
  const y = (v: number) => pad.t + h - ((Math.min(Math.max(v, min), max) - min) / (max - min || 1)) * h;

  const paths = series.map((s) => {
    let d = "";
    let area = "";
    let seg: [number, number][] = [];
    const flush = () => {
      if (seg.length) {
        d += seg.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
        area += `M${seg[0][0].toFixed(1)},${y(Math.max(min, 0)).toFixed(1)}` +
          seg.map(([px, py]) => `L${px.toFixed(1)},${py.toFixed(1)}`).join("") +
          `L${seg[seg.length - 1][0].toFixed(1)},${y(Math.max(min, 0)).toFixed(1)}Z`;
      }
      seg = [];
    };
    s.values.forEach((v, i) => (v === null ? flush() : seg.push([x(i), y(v)])));
    flush();
    return { d, area };
  });

  const xTicks = n > 1 ? [0, Math.floor((n - 1) / 2), n - 1] : [0];
  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = (e.target as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    setHover(Math.max(0, Math.min(n - 1, Math.round((px / Math.max(1, w)) * (n - 1)))));
  };

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && n > 0 ? (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={pad.l + w} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
              <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-3)" className="tabular">
                {format(t)}
              </text>
            </g>
          ))}
          <line x1={pad.l} x2={pad.l + w} y1={pad.t + h} y2={pad.t + h} stroke="var(--axis)" />
          {xTicks.map((i) => (
            <text key={i} x={x(i)} y={height - 6} fontSize={11} fill="var(--ink-3)"
              textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>
              {labels[i]?.slice(11, 16)}
            </text>
          ))}
          {series.map((s, si) => (
            <g key={s.name}>
              <path d={paths[si].area} fill={s.color} opacity={0.08} />
              <path d={paths[si].d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            </g>
          ))}
          {series.map((s) => {
            const lastIdx = s.values.length - 1;
            const v = s.values[lastIdx];
            return v === null || v === undefined || hover !== null ? null : (
              <circle key={s.name} cx={x(lastIdx)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
            );
          })}
          {hover !== null ? (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + h} stroke="var(--ink-3)" strokeWidth={1} />
              {series.map((s) => {
                const v = s.values[hover];
                return v === null || v === undefined ? null : (
                  <circle key={s.name} cx={x(hover)} cy={y(v)} r={4.5} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                );
              })}
            </g>
          ) : null}
          <rect x={pad.l} y={pad.t} width={w} height={h} fill="transparent" onMouseMove={onMove}
            onMouseLeave={() => setHover(null)} />
        </svg>
      ) : null}
      {hover !== null && width > 0 ? (
        <div className="pointer-events-none absolute z-10 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs shadow-xl"
          style={{ left: Math.min(x(hover) + 12, width - 170), top: pad.t }}>
          <div className="mb-1 text-ink-3">{labels[hover]?.replace("T", " ")}</div>
          {series.map((s) => (
            <div key={s.name} className="flex items-center gap-2 text-ink">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} />
              <span className="text-ink-2">{s.name}</span>
              <span className="tabular ml-auto pl-3 font-medium">
                {s.values[hover] === null || s.values[hover] === undefined ? "—" : format(s.values[hover] as number)}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function Sparkline({ values, color = "var(--accent)", height = 36, max = 100 }: {
  values: number[]; color?: string; height?: number; max?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const n = values.length;
  const d = n > 1 && width > 0
    ? values.map((v, i) => `${i ? "L" : "M"}${((i / (n - 1)) * (width - 4) + 2).toFixed(1)},${(height - 3 - (Math.min(v, max) / max) * (height - 6)).toFixed(1)}`).join("")
    : "";
  return (
    <div ref={ref} className="w-full" style={{ height }} aria-hidden="true">
      {d ? (
        <svg width={width} height={height}>
          <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        </svg>
      ) : null}
    </div>
  );
}

export function Meter({ label, value, detail, thresholds = [75, 90] }: {
  label: string; value: number | null; detail?: ReactNode; thresholds?: [number, number];
}) {
  const v = value ?? 0;
  const color = value === null ? "var(--ink-3)" : v >= thresholds[1] ? "var(--critical)" : v >= thresholds[0] ? "var(--warning)" : "var(--accent)";
  const level = value === null ? "" : v >= thresholds[1] ? "Critical" : v >= thresholds[0] ? "High" : "";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-ink-2">{label}</span>
        <span className="tabular font-semibold">
          {value === null ? <span className="text-ink-3">Unknown</span> : `${v.toFixed(0)}%`}
          {level ? <span className="ml-1.5 text-xs font-normal text-ink-3">{level}</span> : null}
        </span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full" role="meter" aria-valuenow={v} aria-valuemin={0}
        aria-valuemax={100} aria-label={label}
        style={{ background: `color-mix(in srgb, ${color} 18%, transparent)` }}>
        <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${Math.min(100, v)}%`, background: color }} />
      </div>
      {detail ? <div className="mt-1 text-xs text-ink-3">{detail}</div> : null}
    </div>
  );
}

export function BarList({ items, color = "var(--accent)", format = (v: number) => v.toLocaleString("en-US"), max, hrefFor, emptyText = "No data" }: {
  items: { name: string; count: number; note?: string }[]; color?: string; format?: (v: number) => string;
  max?: number; hrefFor?: (name: string) => string | null; emptyText?: string;
}) {
  if (!items.length) return <div className="py-6 text-center text-sm text-ink-3">{emptyText}</div>;
  const top = max ?? Math.max(...items.map((i) => i.count), 1);
  return (
    <ul className="flex flex-col gap-2.5">
      {items.map((it) => {
        const href = hrefFor?.(it.name) ?? null;
        const label = <span className="truncate" title={it.name}>{it.name}</span>;
        return (
          <li key={it.name} className="group grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-3 text-sm"
            title={`${it.name}: ${format(it.count)}${it.note ? ` · ${it.note}` : ""}`}>
            {href ? <Link href={href} className="truncate text-ink-2 hover:text-ink hover:underline">{label}</Link> : <span className="truncate text-ink-2">{label}</span>}
            <div className="h-2.5 w-full rounded-full bg-surface-2">
              <div className="h-full rounded-r-[4px] rounded-l-full transition-opacity group-hover:opacity-80"
                style={{ width: `${Math.max(1.5, (it.count / top) * 100)}%`, background: color }} />
            </div>
            <span className="tabular min-w-10 text-right text-ink">{format(it.count)}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function SegmentedBar({ parts, height = 10 }: {
  parts: { name: string; value: number; color: string }[]; height?: number;
}) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  const visible = parts.filter((p) => p.value > 0);
  return (
    <div>
      <div className="flex w-full gap-[2px]" style={{ height }} role="img"
        aria-label={visible.map((p) => `${p.name} ${p.value}`).join(", ")}>
        {total === 0 ? <div className="h-full w-full rounded-full bg-surface-2" /> : visible.map((p, i) => (
          <div key={p.name} title={`${p.name}: ${p.value} (${((p.value / total) * 100).toFixed(1)}%)`}
            className={`h-full ${i === 0 ? "rounded-l-full" : ""} ${i === visible.length - 1 ? "rounded-r-full" : ""}`}
            style={{ width: `${(p.value / total) * 100}%`, background: p.color, minWidth: 3 }} />
        ))}
      </div>
      <div className="mt-3">
        <Legend items={parts.map((p) => ({ name: p.name, color: p.color, value: p.value }))} />
      </div>
    </div>
  );
}

export function StackedColumns({ data, keys, height = 200, ariaLabel }: {
  data: { label: string; values: Record<string, number> }[];
  keys: { key: string; name: string; color: string }[]; height?: number; ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const pad = { l: 36, r: 8, t: 10, b: 24 };
  const w = Math.max(0, width - pad.l - pad.r);
  const h = height - pad.t - pad.b;
  const totals = data.map((d) => keys.reduce((a, k) => a + (d.values[k.key] || 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const band = data.length ? w / data.length : 0;
  const colW = Math.max(2, Math.min(24, band * 0.6));
  const y = (v: number) => (v / max) * h;
  const every = Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(w / 48))));
  const ticks = max <= 2 ? [0, max] : [0, 0.5, 1].map((f) => f * max);  // kichik sonlarda takroriy yozuv bo'lmasin
  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 ? (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={pad.l + w} y1={pad.t + h - y(t)} y2={pad.t + h - y(t)} stroke="var(--grid)" />
              <text x={pad.l - 8} y={pad.t + h - y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-3)" className="tabular">
                {Math.round(t)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = pad.l + band * i + band / 2;
            let acc = 0;
            const segs = keys.filter((k) => (d.values[k.key] || 0) > 0);
            return (
              <g key={d.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={pad.l + band * i} y={pad.t} width={band} height={h} fill={hover === i ? "var(--surface-2)" : "transparent"} />
                {segs.map((k, si) => {
                  const v = d.values[k.key] || 0;
                  const segH = Math.max(1, y(v) - (si > 0 ? 2 : 0));
                  const top = pad.t + h - y(acc) - y(v);
                  acc += v;
                  const isTop = si === segs.length - 1;
                  const r = isTop ? Math.min(4, segH / 2, colW / 2) : 0;
                  const x0 = cx - colW / 2;
                  const yb = top + segH;
                  const path = `M${x0},${yb}V${top + r}${r ? `Q${x0},${top} ${x0 + r},${top}` : ""}H${x0 + colW - r}${r ? `Q${x0 + colW},${top} ${x0 + colW},${top + r}` : ""}V${yb}Z`;
                  return <path key={k.key} d={path} fill={k.color} />;
                })}
                {i % every === 0 ? (
                  <text x={cx} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--ink-3)">{d.label}</text>
                ) : null}
              </g>
            );
          })}
          <line x1={pad.l} x2={pad.l + w} y1={pad.t + h} y2={pad.t + h} stroke="var(--axis)" />
        </svg>
      ) : null}
      {hover !== null && data[hover] ? (
        <div className="pointer-events-none absolute z-10 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs shadow-xl"
          style={{ left: Math.min(pad.l + band * hover + band / 2 + 12, width - 150), top: 0 }}>
          <div className="mb-1 text-ink-3">{data[hover].label}</div>
          {keys.map((k) => (
            <div key={k.key} className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ background: k.color }} />
              <span className="text-ink-2">{k.name}</span>
              <span className="tabular ml-auto pl-3 font-medium text-ink">{data[hover].values[k.key] || 0}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function TableView({ rows, columns }: { rows: Record<string, ReactNode>[]; columns: { key: string; label: string }[] }) {
  return (
    <details className="no-print mt-4 text-sm">
      <summary className="cursor-pointer select-none text-xs text-ink-3 hover:text-ink-2">Table view</summary>
      <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs">
          <thead>
            <tr>{columns.map((c) => <th key={c.key} className="sticky top-0 bg-surface-2 px-3 py-2 font-medium text-ink-3">{c.label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-line/60">
                {columns.map((c) => <td key={c.key} className="tabular px-3 py-1.5 text-ink-2">{r[c.key]}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
