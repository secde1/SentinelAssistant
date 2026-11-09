"use client";

import { useState } from "react";
import { Card, ErrorBox, PageHeader } from "@/components/ui";
import { Badge, DataTable, Drawer, SkeletonRows, type Col } from "@/components/kit";
import { ago, timeOnly } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Member { id: string; title: string; unit: string; last_ts: string | null; active: boolean; task?: string | null; counters?: Record<string, number> }
interface Msg { id: number; ts: string; role: string; kind: string; text: string; ref: string | null }

export default function AgentsPage() {
  usePageTitle("Agentlar");
  const staff = useApi<{ members: Member[] }>("/api/desk/staff", 5000);
  const msgs = useApi<{ items: Msg[] }>("/api/desk/messages", 8000);
  const [sel, setSel] = useState<Member | null>(null);
  const items = msgs.data?.items ?? [];
  const count = (id: string) => items.filter((m) => m.role === id).length;

  const cols: Col<Member>[] = [
    { key: "id", label: "Agent ID", sort: (r) => r.id, className: "font-mono text-xs font-semibold", render: (r) => r.id },
    { key: "t", label: "Roli", sort: (r) => r.title, render: (r) => r.title },
    { key: "u", label: "Bo'lim", sort: (r) => r.unit, className: "text-xs text-ink-3", render: (r) => r.unit },
    { key: "s", label: "Holat", sort: (r) => (r.active ? 1 : 0), render: (r) => <Badge tone={r.active ? "good" : "mute"}>{r.active ? "WORKING" : r.last_ts ? "ONLINE" : "kutmoqda"}</Badge> },
    { key: "l", label: "Oxirgi faollik", sort: (r) => r.last_ts, className: "text-xs text-ink-3", render: (r) => (r.last_ts ? ago(r.last_ts) : "hali yo'q") },
    { key: "task", label: "Oxirgi / hozirgi ish", className: "max-w-[420px] text-xs text-ink-2", render: (r) => r.task ?? "hali ish yo'q" },
    { key: "z", label: "Zona / aktiv", className: "tabular text-xs", render: (r) => (r.counters?.zones !== undefined ? `${r.counters.zones} / ${r.counters.active ?? 0}` : "—") },
    { key: "c", label: "Xabarlar (oxirgi 80 ichida)", sort: (r) => count(r.id), className: "tabular", render: (r) => count(r.id) },
  ];
  const log = sel ? items.filter((m) => m.role === sel.id).reverse() : [];

  return (
    <>
      <PageHeader title="Agentlar" subtitle="Claude xodimlari reestri. Xodim faqat signal muhokamasi yoki audit paytida ishlaydi; boshqa vaqtda 'kutmoqda' — bu normal." />
      <Drawer open={!!sel} onClose={() => setSel(null)} title={sel?.id ?? ""} subtitle={sel?.title}>
        {log.length ? log.map((m) => (
          <div key={m.id} className="mb-2 rounded-lg border border-line bg-surface-2 p-3 text-xs">
            <div className="mb-1 font-mono text-[11px] text-ink-3">{timeOnly(m.ts)} · {m.kind}{m.ref ? ` · ${m.ref}` : ""}</div>
            <div className="whitespace-pre-wrap break-words text-ink-2">{m.text}</div>
          </div>
        )) : <div className="py-10 text-center text-sm text-ink-3">Bu xodimdan hali xabar yo&apos;q.</div>}
      </Drawer>
      {staff.error ? <ErrorBox error={staff.error} /> : (
        <Card bodyClass="p-0">
          {staff.loading && !staff.data ? <SkeletonRows /> : <DataTable rows={staff.data?.members ?? []} cols={cols} rowKey={(r) => r.id} onRow={setSel} search={(r) => `${r.id} ${r.title}`} empty="Xodimlar yo'q." />}
        </Card>
      )}
    </>
  );
}
