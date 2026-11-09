"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { IconChevron, IconSearch, IconX } from "./icons";

/* ---------- Skeleton / holatlar ---------- */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2.5 p-4" role="status" aria-label="Yuklanmoqda">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-7 w-full" />)}
    </div>
  );
}

/* ---------- Toast ---------- */
type ToastTone = "ok" | "error" | "info";
interface ToastItem { id: number; text: string; tone: ToastTone }
const ToastCtx = createContext<(text: string, tone?: ToastTone) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: ToastTone = "info") => {
    const id = Date.now() + Math.random();
    setItems((p) => [...p.slice(-3), { id, text, tone }]);
    setTimeout(() => setItems((p) => p.filter((t) => t.id !== id)), 5000);
  }, []);
  const color = { ok: "var(--good)", error: "var(--critical)", info: "var(--accent)" };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="no-print pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="toast-in pointer-events-auto rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm shadow-xl"
            style={{ borderLeft: `3px solid ${color[t.tone]}` }}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- Drawer ---------- */
export function Drawer({ open, onClose, title, subtitle, children, width = "max-w-xl" }: {
  open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="no-print fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <aside className={`drawer-in relative flex h-full w-full ${width} flex-col border-l border-line bg-surface`}>
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{title}</h2>
            {subtitle ? <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p> : null}
          </div>
          <button onClick={onClose} aria-label="Yopish" className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink"><IconX /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

/* ---------- Badge / nuqta ---------- */
const TONES = {
  good: "border-good/40 bg-good/10 text-good", bad: "border-critical/40 bg-critical/10 text-critical",
  warn: "border-warning/40 bg-warning/10 text-warning", info: "border-accent/40 bg-accent/10 text-accent",
  mute: "border-line bg-surface-2 text-ink-3",
} as const;
export type Tone = keyof typeof TONES;
export function Badge({ tone = "mute", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${TONES[tone]}`}>{children}</span>;
}

export function SideBadge({ side }: { side: string | null | undefined }) {
  const s = (side ?? "").toUpperCase();
  const buy = s === "LONG" || s === "BUY";
  const sell = s === "SHORT" || s === "SELL";
  return <Badge tone={buy ? "good" : sell ? "bad" : "mute"}>{buy ? "BUY" : sell ? "SELL" : s || "—"}</Badge>;
}

export function Dot({ on, pulse }: { on: boolean | null | undefined; pulse?: boolean }) {
  const c = on === null || on === undefined ? "var(--ink-3)" : on ? "var(--good)" : "var(--critical)";
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${pulse && on ? "desk-blink" : ""}`} style={{ background: c }} />;
}

/* ---------- KPI plitka ---------- */
export function Kpi({ label, value, sub, tone, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad"; icon?: ReactNode }) {
  return (
    <div className="panel rounded-xl border border-line p-4 transition-colors hover:border-accent/40">
      <div className="flex items-center gap-2 text-xs text-ink-3"><span className="text-accent">{icon}</span>{label}</div>
      <div className={`tabular mt-2 text-2xl font-semibold tracking-tight ${tone === "good" ? "text-good" : tone === "bad" ? "text-critical" : ""}`}>{value}</div>
      {sub ? <div className="mt-1 text-[11px] text-ink-3">{sub}</div> : null}
    </div>
  );
}

/* ---------- Saralanadigan, qidiriladigan jadval ---------- */
export interface Col<T> {
  key: string; label: string; sort?: (r: T) => string | number | null; render: (r: T) => ReactNode; className?: string;
}

export function DataTable<T>({ rows, cols, rowKey, onRow, search, filters, empty = "Ma'lumot yo'q", pageSize = 25 }: {
  rows: T[]; cols: Col<T>[]; rowKey: (r: T) => string; onRow?: (r: T) => void;
  search?: (r: T) => string; filters?: { label: string; options: string[]; pick: (r: T) => string }[]; empty?: ReactNode; pageSize?: number;
}) {
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [dir, setDir] = useState<1 | -1>(-1);
  const [fv, setFv] = useState<Record<string, string>>({});
  const [page, setPage] = useState(0);

  const view = useMemo(() => {
    let r = rows;
    if (q && search) { const n = q.toLowerCase(); r = r.filter((x) => search(x).toLowerCase().includes(n)); }
    (filters ?? []).forEach((f) => { const v = fv[f.label]; if (v) r = r.filter((x) => f.pick(x) === v); });
    const c = cols.find((x) => x.key === sortKey);
    if (c?.sort) {
      const g = c.sort;
      r = [...r].sort((a, b) => {
        const x = g(a), y = g(b);
        if (x === y) return 0;
        if (x === null) return 1;
        if (y === null) return -1;
        return (x > y ? 1 : -1) * dir;
      });
    }
    return r;
  }, [rows, q, fv, sortKey, dir, cols, search, filters]);

  const pages = Math.max(1, Math.ceil(view.length / pageSize));
  const cur = Math.min(page, pages - 1);
  const slice = view.slice(cur * pageSize, (cur + 1) * pageSize);

  return (
    <div>
      {(search || filters?.length) ? (
        <div className="no-print flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          {search ? (
            <label className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-ink-3">
              <IconSearch width={14} height={14} />
              <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Qidirish…" aria-label="Qidirish"
                className="w-44 bg-transparent text-ink outline-none placeholder:text-ink-3" />
            </label>
          ) : null}
          {(filters ?? []).map((f) => (
            <select key={f.label} value={fv[f.label] ?? ""} aria-label={f.label} onChange={(e) => { setFv({ ...fv, [f.label]: e.target.value }); setPage(0); }}
              className="rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-ink">
              <option value="">{f.label}: hammasi</option>
              {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ))}
          <span className="ml-auto text-xs text-ink-3">{view.length} ta</span>
        </div>
      ) : null}
      {!view.length ? <div className="px-2 py-10 text-center text-sm text-ink-3">{empty}</div> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-left text-sm">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c.key} className="sticky top-0 whitespace-nowrap border-b border-line bg-surface px-3 py-2.5 text-[11px] font-medium uppercase tracking-wide text-ink-3">
                    {c.sort ? (
                      <button className="inline-flex items-center gap-1 hover:text-ink" onClick={() => { if (sortKey === c.key) setDir(dir === 1 ? -1 : 1); else { setSortKey(c.key); setDir(-1); } }}>
                        {c.label}
                        {sortKey === c.key ? <IconChevron width={12} height={12} className={dir === 1 ? "-rotate-90" : "rotate-90"} /> : null}
                      </button>
                    ) : c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <tr key={rowKey(r)} onClick={onRow ? () => onRow(r) : undefined}
                  className={`border-b border-line/50 transition-colors hover:bg-surface-2 ${onRow ? "cursor-pointer" : ""}`}>
                  {cols.map((c) => <td key={c.key} className={`px-3 py-2.5 align-middle ${c.className ?? ""}`}>{c.render(r)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 ? (
        <div className="no-print flex items-center justify-between px-4 py-3 text-xs text-ink-3">
          <span>{cur + 1} / {pages}</span>
          <div className="flex gap-2">
            <button disabled={cur === 0} onClick={() => setPage(cur - 1)} className="rounded-md border border-line px-2.5 py-1 hover:bg-surface-2 disabled:opacity-40">Oldingi</button>
            <button disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)} className="rounded-md border border-line px-2.5 py-1 hover:bg-surface-2 disabled:opacity-40">Keyingi</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export const num = (n: number | null | undefined, d = 2) => (typeof n === "number" && Number.isFinite(n) ? n.toFixed(d) : "N/A");
export const signTone = (n: number | null | undefined) => (typeof n === "number" ? (n > 0 ? "text-good" : n < 0 ? "text-critical" : "") : "");
