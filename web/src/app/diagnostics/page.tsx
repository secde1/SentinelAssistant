"use client";

import { Card, ErrorBox, PageHeader } from "@/components/ui";
import { Badge, Dot, Kpi, SkeletonRows, type Tone } from "@/components/kit";
import { ago, dateTime } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Comp { id: string; name: string; status: "ok" | "warn" | "down" | "unknown"; last_activity: string | null; last_error: string | null; processing_ms: number | null; executions: number | null; failures: number | null; detail: string }
interface Diag {
  ts: string; components: Comp[]; funnel: Record<string, number>; reasons: { stage: string; strategy: string; reason: string; n: number }[];
  tasks: { kind: string; name: string; detail: string | null; ts: string | null }[]; build_ms?: number;
}

const TONE: Record<string, Tone> = { ok: "good", warn: "warn", down: "bad", unknown: "mute" };
const LABEL: Record<string, string> = { ok: "OK", warn: "OGOHLANTIRISH", down: "ISHLAMAYAPTI", unknown: "NOMA'LUM" };
const FUNNEL: [string, string][] = [
  ["scans", "Skanlar (24 soat)"], ["scanned", "Tekshirilgan instrument"], ["no_setup", "Nomzod yo'q"], ["data_unavailable", "Ma'lumot yo'q/xato"],
  ["watch", "WATCH (yuborilmaydi)"], ["dropped", "Tashlandi (ball<4)"], ["blocked", "Bloklandi"], ["duplicate", "Takroriy/kuldaun"],
  ["sent", "Signal yuborildi"], ["staff_rejected", "Bahs rad etdi"], ["demo_refused", "Ijro/risk rad etdi"], ["demo_opened", "MT5 DEMO ochildi"], ["zone_signals", "Zona signallari"],
];

export default function DiagnosticsPage() {
  usePageTitle("Diagnostika");
  const { data, error, loading } = useApi<Diag>("/api/desk/diagnostics", 20000);
  return (
    <>
      <PageHeader title="System Diagnostics" subtitle="Hamma qiymat haqiqiy monitoring ma'lumotidan (baza, jurnal, Binance/MT5 zondlari). Ma'lumot bo'lmasa — «noma'lum», soxta OK emas." />
      {error ? <ErrorBox error={error} /> : null}
      <Card title="Komponentlar" subtitle={data ? `Yangilangan: ${dateTime(data.ts)} (Toshkent) · ${data.build_ms ?? "—"} ms` : undefined} bodyClass="p-0" className="mb-4">
        {loading && !data ? <SkeletonRows rows={10} /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead><tr className="text-left text-[11px] uppercase tracking-wide text-ink-3">
                <th className="px-4 py-2.5">Komponent</th><th>Holat</th><th>So&apos;nggi faollik</th><th>Ish vaqti</th><th>Bajarilgan</th><th>Xatolar</th><th>So&apos;nggi xato</th><th className="pr-4">Tafsilot</th></tr></thead>
              <tbody>{(data?.components ?? []).map((c) => (
                <tr key={c.id} className="border-t border-line/50 align-top hover:bg-surface-2">
                  <td className="px-4 py-2.5 font-semibold"><span className="inline-flex items-center gap-2"><Dot on={c.status === "ok" ? true : c.status === "unknown" ? null : false} />{c.name}</span></td>
                  <td><Badge tone={TONE[c.status]}>{LABEL[c.status]}</Badge></td>
                  <td className="whitespace-nowrap text-xs text-ink-2">{c.last_activity ? <>{ago(c.last_activity)}<div className="text-ink-3">{dateTime(c.last_activity)}</div></> : "N/A"}</td>
                  <td className="tabular text-xs">{c.processing_ms !== null ? `${c.processing_ms} ms` : "N/A"}</td>
                  <td className="tabular text-xs">{c.executions ?? "N/A"}</td>
                  <td className={`tabular text-xs ${c.failures ? "text-critical" : ""}`}>{c.failures ?? "N/A"}</td>
                  <td className="max-w-[240px] text-xs text-critical">{c.last_error ? <span title={c.last_error}>{c.last_error.slice(0, 110)}</span> : <span className="text-ink-3">—</span>}</td>
                  <td className="max-w-[320px] pr-4 text-xs text-ink-3">{c.detail}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {FUNNEL.map(([k, label]) => <Kpi key={k} label={label} value={data ? (data.funnel[k] ?? 0) : "N/A"} />)}
      </div>
      {data && !data.funnel.scans ? <p className="mb-4 text-xs text-warning">Skaner izi (scan_log) hali yo&apos;q: agent yangi nusxada birinchi skanini tugatgach to&apos;ldiriladi. Eski skanlar uchun voronka hisoblagichlari saqlanmagan edi.</p> : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Rad etish sabablari (24 soat)" subtitle="Aniq sabablar kod shartlaridan" bodyClass="p-0">
          {!data?.reasons.length ? <div className="p-5 text-sm text-ink-3">Rad etilgan yozuv yo&apos;q yoki scan_log hali bo&apos;sh.</div> : (
            <table className="w-full text-xs"><tbody>{data.reasons.map((r, i) => (
              <tr key={i} className="border-t border-line/50"><td className="px-4 py-2 tabular text-ink-2">{r.n}×</td><td className="font-mono text-ink-3">{r.stage}{r.strategy !== "-" ? ` · ${r.strategy}` : ""}</td><td className="pr-4 text-ink-2">{r.reason}</td></tr>))}</tbody></table>
          )}
        </Card>
        <Card title="Faol fon vazifalari" subtitle="Hozir bajarilayotgan / kutilayotgan" bodyClass="p-0">
          {!data?.tasks.length ? <div className="p-5 text-sm text-ink-3">Hozir faol vazifa yo&apos;q.</div> : (
            <table className="w-full text-xs"><tbody>{data.tasks.map((t, i) => (
              <tr key={i} className="border-t border-line/50"><td className="px-4 py-2"><Badge tone="info">{t.kind}</Badge></td><td className="font-mono">{t.name}</td><td className="pr-4 text-ink-3">{(t.detail ?? "").slice(0, 90)}</td></tr>))}</tbody></table>
          )}
        </Card>
      </div>
    </>
  );
}
