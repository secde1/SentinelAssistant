"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { Badge, Kpi, SkeletonRows } from "@/components/kit";
import { EXEC_TONE } from "@/lib/execStatus";
import { useApi } from "@/lib/hooks";

interface Win {
  counters: Record<string, number>;
  funnel: { stage: string; label: string; n: number }[];
  stopped_at: { status: string; n: number }[];
  reasons: { kind: string; reason: string; n: number }[];
}
interface Data { windows: Record<string, Win>; note?: string; error?: string }

const WINDOWS: [string, string][] = [["today", "Bugun (Toshkent)"], ["7d", "7 kun"], ["all", "Hammasi"]];
const KPIS: [string, string, string?][] = [
  ["generated", "Generated Signals", "WATCH ham"], ["debate_approved", "Debate Approved"], ["debate_rejected", "Debate Rejected"],
  ["risk_approved", "Risk Approved"], ["risk_refused", "Risk Refused"], ["execution_ready", "Execution Ready"],
  ["mt5_executed", "MT5 Executed", "avto/qo'lda"], ["manual_test_orders", "Manual Test Orders", "avtomatikka sanalmaydi"],
  ["expired_invalidated", "Expired / Invalidated"],
];

/** Ijro voronkasi: signal qayerda to'xtaydi. Hamma son bazadan (signals + signal_events + execution_audit). */
export function ExecutionFunnel() {
  const { data, error, loading } = useApi<Data>("/api/desk/execution", 20000);
  const [win, setWin] = useState("today");
  const w = data?.windows?.[win];
  const max = Math.max(1, ...(w?.funnel.map((f) => f.n) ?? [1]));
  return (
    <Card title="Ijro voronkasi" subtitle={data?.note ?? "Signal qayerda to'xtashi"} className="mb-4"
      actions={<div className="flex gap-1">{WINDOWS.map(([k, l]) => (
        <button key={k} onClick={() => setWin(k)} className={`rounded-md border px-2.5 py-1 text-xs ${win === k ? "border-accent bg-accent/10 text-accent" : "border-line text-ink-3 hover:text-ink"}`}>{l}</button>))}</div>}>
      {error || data?.error ? <div className="text-sm text-critical">{error ?? data?.error}</div> : loading && !w ? <SkeletonRows rows={4} /> : !w ? <div className="text-sm text-ink-3">Ma&apos;lumot yo&apos;q.</div> : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            {KPIS.map(([k, label, sub]) => <Kpi key={k} label={label} value={w.counters[k] ?? 0} sub={sub} tone={k === "mt5_executed" && (w.counters[k] ?? 0) > 0 ? "good" : undefined} />)}
          </div>
          {w.counters.owner_override_after_reject ? <p className="mb-3 text-xs text-warning">Bahs rad etgan, lekin egasi HA bosgan signallar: {w.counters.owner_override_after_reject} (ijro baribir xavf nazoratidan o&apos;tadi).</p> : null}
          <div className="grid gap-5 xl:grid-cols-2">
            <div>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Konversiya voronkasi</h3>
              <ul className="flex flex-col gap-2">{w.funnel.map((f, i) => {
                const prev = i ? w.funnel[i - 1].n : null;
                return (
                  <li key={f.stage} className="text-sm">
                    <div className="mb-0.5 flex justify-between"><span className="text-ink-2">{f.label}</span>
                      <span className="tabular font-mono">{f.n}{prev ? <span className="ml-2 text-[11px] text-ink-3">({Math.round((100 * f.n) / prev)}% oldingisidan)</span> : null}</span></div>
                    <div className="h-2 overflow-hidden rounded bg-surface-3"><div className="h-full rounded bg-accent" style={{ width: `${(100 * f.n) / max}%` }} /></div>
                  </li>);
              })}</ul>
              <p className="mt-2 text-[11px] text-ink-3">Bosqichlar o&apos;zaro qat&apos;iy ketma-ket emas (egasi bahsdan keyin ham HA bosishi mumkin); har signal yakuniy holati bo&apos;yicha o&apos;ngda.</p>
            </div>
            <div>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Qayerda to&apos;xtadi (yakuniy holat)</h3>
              {!w.stopped_at.length ? <div className="text-sm text-ink-3">Hammasi ijro qilingan yoki signal yo&apos;q.</div> : (
                <ul className="mb-3 flex flex-wrap gap-2">{w.stopped_at.map((s) => <li key={s.status}><Badge tone={EXEC_TONE[s.status] ?? "mute"}>{s.status} · {s.n}</Badge></li>)}</ul>)}
              <h3 className="mb-2 mt-3 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Aniq sabablar</h3>
              {!w.reasons.length ? <div className="text-sm text-ink-3">Rad etish yozuvi yo&apos;q.</div> : (
                <table className="w-full text-xs"><tbody>{w.reasons.map((r, i) => (
                  <tr key={i} className="border-t border-line/50 align-top"><td className="py-1.5 pr-2 tabular text-ink-2">{r.n}×</td><td className="pr-2 font-mono text-ink-3">{r.kind}</td><td className="text-ink-2">{r.reason}</td></tr>))}</tbody></table>)}
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
