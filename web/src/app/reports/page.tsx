"use client";

import { useState } from "react";
import { Card, ErrorBox, PageHeader, Tabs } from "@/components/ui";
import { Badge, SkeletonRows } from "@/components/kit";
import { dateTime } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Report { report_id: string; kind: string; period_start: string; period_end: string; created_at: string; text: string }
interface Msg { id: number; ts: string; role: string; kind: string; text: string; ref: string | null }

export default function ReportsPage() {
  usePageTitle("Hisobotlar");
  const rep = useApi<{ items: Report[] }>("/api/trading/reports", 60000);
  const msgs = useApi<{ items: Msg[] }>("/api/desk/messages", 15000);
  const [tab, setTab] = useState<"audit" | "research">("audit");
  const audits = (msgs.data?.items ?? []).filter((m) => m.kind === "audit" || m.kind === "verdict" || m.kind === "decision").reverse();

  return (
    <>
      <PageHeader title="Hisobotlar" subtitle="AUDIT-1 tahlillari va bo'lim qarorlari; tadqiqot (Research) hisobotlari." />
      <div className="mb-4"><Tabs value={tab} onChange={setTab} items={[{ value: "audit", label: "Audit va qarorlar", count: audits.length }, { value: "research", label: "Research hisobotlari", count: rep.data?.items.length }]} /></div>
      {tab === "audit" ? (
        msgs.error ? <ErrorBox error={msgs.error} /> : msgs.loading && !msgs.data ? <Card><SkeletonRows /></Card> : !audits.length ? <Card><div className="py-10 text-center text-sm text-ink-3">Hali audit yoki qaror yo&apos;q.</div></Card> : (
          <div className="flex flex-col gap-3">{audits.map((m) => (
            <Card key={m.id} bodyClass="p-4">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs"><span className="font-mono font-semibold text-accent">{m.role}</span><Badge tone={m.kind === "audit" ? "warn" : "info"}>{m.kind}</Badge>{m.ref ? <span className="font-mono text-ink-3">{m.ref}</span> : null}<span className="ml-auto text-ink-3">{dateTime(m.ts)}</span></div>
              <div className="whitespace-pre-wrap break-words text-sm text-ink-2">{m.text}</div>
            </Card>))}</div>
        )
      ) : rep.error ? <ErrorBox error={rep.error} /> : rep.loading && !rep.data ? <Card><SkeletonRows /></Card> : !rep.data?.items.length ? <Card><div className="py-10 text-center text-sm text-ink-3">Research hisobotlari hali yo&apos;q.</div></Card> : (
        <div className="flex flex-col gap-3">{rep.data.items.map((r) => (
          <Card key={r.report_id} title={`${r.kind} · ${r.period_start?.slice(0, 10)} → ${r.period_end?.slice(0, 10)}`} subtitle={`Yaratilgan: ${dateTime(r.created_at)}`} bodyClass="p-4">
            <pre className="whitespace-pre-wrap break-words font-sans text-sm text-ink-2">{r.text}</pre>
          </Card>))}</div>
      )}
    </>
  );
}
