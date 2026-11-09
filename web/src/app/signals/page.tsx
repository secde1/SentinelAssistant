"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, ErrorBox, PageHeader } from "@/components/ui";
import { Badge, DataTable, Drawer, SideBadge, SkeletonRows, Skeleton, num, useToast, type Col, type Tone } from "@/components/kit";
import { api } from "@/lib/api";
import { ExecutionFunnel } from "@/components/ExecutionFunnel";
import { EXEC_TONE, ORIGIN_LABEL } from "@/lib/execStatus";
import { dateTime, timeOnly } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Staff { approve: boolean; reason: string; votes: Record<string, string> }
interface Sig {
  signal_id: string; created_at: string; symbol: string; timeframe: string | null; direction: string; strategy_id: string | null;
  entry: number | null; sl: number | null; tp: number | null; rr: number | null; score: number | null; tier: string | null;
  status: string; decided_by: number | null; decision_note: string | null; staff: Staff | null;
  exec_status?: string; origin?: string | null;
}
interface Item { key: string; label: string; ok: boolean | null; detail: string }
interface Detail {
  signal: Sig & { strategy_version: number | null; entry_type: string | null; rr_net: number | null; valid_until: string | null; data_source: string | null; data_ts: string | null;
    analysis: { items?: Item[]; structure?: string; evidence?: Record<string, number | string>; blocked?: string | null; missing?: string[]; spread?: number; commission?: number } | null;
    invalidation: { text?: string; level?: number } | null };
  events: { ts: string; kind: string; detail: string }[];
  messages: { id: number; ts: string; role: string; kind: string; text: string }[];
  decision: { approve: number; votes: string; reason: string } | null;
  execution_audit?: { ts: string; origin: string | null; debate_result: string | null; risk_result: string | null; decision: string; stage: string; reason: string | null; mt5_request: string | null; mt5_retcode: number | null }[];
}

const TIER_TONE: Record<string, Tone> = { ZONE: "info", STRONG: "good", CONFIRM: "info", WATCH: "warn", DROP: "mute", BLOCKED: "bad" };
const STATUS_TONE: Record<string, Tone> = { SENT: "info", CONFIRMED: "info", CONFIRMING: "info", REJECTED: "bad", REFUSED: "bad", EXPIRED: "mute", INVALIDATED: "mute" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">{title}</h3>{children}</section>;
}

function DetailView({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<Detail>(`/api/desk/signal?id=${encodeURIComponent(id)}`).then((r) => { setD(r); setErr(null); }).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function act(cmd: "review" | "confirm" | "reject") {
    const ask = { review: "Jamoa muhokama qilsin; ruxsat bersa DEMO zdelka ochiladi (himoyalar tekshiriladi). Davom etasizmi?",
      confirm: "HA: DEMO zdelka ochilsinmi? (Telegram'dagi HA tugmasi bilan bir xil, himoyalar tekshiriladi)", reject: "YO'Q: signal rad etilsinmi?" }[cmd];
    if (!window.confirm(ask)) return;
    setBusy(true);
    try {
      const r = await api.post<{ id: number }>("/api/desk/command", { cmd, arg: id });
      toast(`Buyruq #${r.id} navbatda…`, "info");
      for (let i = 0; i < 40; i++) {
        await new Promise((x) => setTimeout(x, 1500));
        const st = await api.get<{ status: string; result: string | null }>(`/api/desk/command?id=${r.id}`);
        if (st.status !== "pending") {
          toast(`${cmd}: ${st.result ?? st.status}`, st.status === "done" ? "ok" : "error");
          break;
        }
      }
      load();
      onChanged();
    } catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); } finally { setBusy(false); }
  }

  if (err) return <ErrorBox error={err} />;
  if (!d) return <div className="flex flex-col gap-3"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-24 w-full" /><Skeleton className="h-40 w-full" /></div>;
  const s = d.signal;
  const a = s.analysis;
  const votes = d.decision ? (JSON.parse(d.decision.votes || "{}") as Record<string, string>) : null;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <SideBadge side={s.direction} /><Badge tone={TIER_TONE[s.tier ?? ""] ?? "mute"}>{s.tier ?? "—"}</Badge>
        <Badge tone={EXEC_TONE[s.exec_status ?? ""] ?? STATUS_TONE[s.status] ?? "mute"}>{s.exec_status ?? s.status}</Badge>
        <span className="text-[11px] text-ink-3" title="Eski holat (orqaga moslik): CONFIRMED ijro degani emas">holat: {s.status}</span>
        {s.origin ? <Badge tone={s.origin === "forced_test" ? "warn" : "info"}>{ORIGIN_LABEL[s.origin] ?? s.origin}</Badge> : null}
      </div>
      <div className="grid grid-cols-3 gap-3 text-sm">
        {([["Entry", s.entry], ["Stop Loss", s.sl], ["Take Profit", s.tp], ["R/R", s.rr], ["R/R (net)", s.rr_net], ["Score", s.score]] as [string, number | null][]).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-line bg-surface-2 p-3"><div className="text-[11px] text-ink-3">{k}</div><div className="tabular font-mono">{typeof v === "number" ? v : "N/A"}</div></div>
        ))}
      </div>

      {s.status === "SENT" ? (
        <Section title="Qaror (egasi)">
          <div className="flex flex-wrap gap-2">
            <button disabled={busy} onClick={() => act("confirm")} className="rounded-lg bg-good px-4 py-2 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50">HA — {s.direction === "SHORT" ? "SELL" : "BUY"}</button>
            <button disabled={busy} onClick={() => act("reject")} className="rounded-lg bg-critical px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">YO&apos;Q</button>
            <button disabled={busy} onClick={() => act("review")} className="rounded-lg border border-line bg-surface-2 px-4 py-2 text-sm hover:bg-surface-3 disabled:opacity-50">Jamoaga topshirish</button>
          </div>
          <p className="mt-2 text-[11px] text-ink-3">HA/YO&apos;Q Telegram tugmasi bilan bir xil yo&apos;ldan o&apos;tadi: faqat DEMO, lot/SL/limit himoyalari agent tomonida tekshiriladi.</p>
        </Section>
      ) : null}

      <Section title="Technical analysis">
        {a?.items?.length ? (
          <ul className="flex flex-col gap-1.5 text-sm">
            {a.items.map((it) => (
              <li key={it.key} className="flex items-start gap-2"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${it.ok === null ? "bg-ink-3" : it.ok ? "bg-good" : "bg-critical"}`} />
                <span><span className="text-ink-2">{it.label}:</span> <span className="text-ink-3">{it.detail}</span></span></li>
            ))}
          </ul>
        ) : <div className="text-sm text-ink-3">Ma&apos;lumot yo&apos;q.</div>}
        {a?.blocked ? <div className="mt-2 text-sm text-critical">Bloklangan: {a.blocked}</div> : null}
        {a?.missing?.length ? <div className="mt-2 text-xs text-warning">Yetishmayotgan: {a.missing.join(", ")}</div> : null}
      </Section>

      <Section title="Market structure">
        <div className="text-sm text-ink-2">{a?.structure ?? "Ma'lumot yo'q."}</div>
        {a?.evidence ? <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px] text-ink-3">{Object.entries(a.evidence).map(([k, v]) => <div key={k}>{k}: <span className="text-ink-2">{String(v)}</span></div>)}</div> : null}
      </Section>

      <Section title="Strategy explanation">
        <div className="text-sm text-ink-2">{s.strategy_id ?? "N/A"}{s.strategy_version ? ` v${s.strategy_version}` : ""} · {s.timeframe ?? "?"} · kirish turi: {s.entry_type ?? "N/A"}</div>
        {s.invalidation?.text ? <div className="mt-1 text-xs text-ink-3">Bekor bo&apos;lish sharti: {s.invalidation.text}{s.invalidation.level ? ` (${s.invalidation.level})` : ""}</div> : null}
      </Section>

      <Section title="Risk assessment">
        <div className="grid grid-cols-2 gap-2 text-sm text-ink-2">
          <div>Spread: <span className="font-mono">{a?.spread ?? "N/A"}</span></div><div>Komissiya: <span className="font-mono">{a?.commission ?? "N/A"}</span></div>
          <div>Amal muddati: {s.valid_until ? dateTime(s.valid_until) : "N/A"}</div><div>Manba: {s.data_source ?? "N/A"}</div>
        </div>
      </Section>

      <Section title="Agent discussion">
        {d.decision ? (
          <div className={`mb-3 rounded-lg border p-3 text-sm ${d.decision.approve ? "border-good/40 bg-good/10" : "border-critical/40 bg-critical/10"}`}>
            <div className="font-semibold">{d.decision.approve ? "Ruxsat berildi" : "Rad etildi"}{votes ? ` · ${Object.values(votes).filter((v) => v === "approve").length}/${Object.keys(votes).length} ovoz` : ""}</div>
            <div className="mt-1 text-xs text-ink-2">{d.decision.reason}</div>
          </div>
        ) : null}
        {!d.messages.length ? <div className="text-sm text-ink-3">Bu signal bo&apos;yicha bo&apos;lim muhokamasi bo&apos;lmagan.</div> : d.messages.map((m) => (
          <div key={m.id} className="mb-2 rounded-lg border border-line bg-surface-2 p-3 text-xs">
            <div className="mb-1 font-mono text-[11px] text-accent">{m.role} <span className="text-ink-3">· {timeOnly(m.ts)}</span></div>
            <div className="whitespace-pre-wrap break-words text-ink-2">{m.text}</div>
          </div>
        ))}
      </Section>

      {d.execution_audit?.length ? (
        <Section title="Ijro jurnali (execution audit)">
          <div className="overflow-x-auto"><table className="w-full text-[11px]"><thead><tr className="text-left text-ink-3"><th className="pr-2">UTC</th><th className="pr-2">Qaror</th><th className="pr-2">Bosqich</th><th className="pr-2">Bahs</th><th className="pr-2">Risk</th><th className="pr-2">MT5 so&apos;rov</th><th>Sabab</th></tr></thead>
            <tbody>{d.execution_audit.map((e, i) => (
              <tr key={i} className="border-t border-line/50 align-top"><td className="whitespace-nowrap pr-2 font-mono text-ink-3">{e.ts.slice(11, 19)}</td><td className="pr-2 font-semibold">{e.decision}</td><td className="pr-2 font-mono">{e.stage}</td>
                <td className="pr-2">{e.debate_result ?? "—"}</td><td className="pr-2">{e.risk_result ?? "—"}</td><td className="pr-2 font-mono">{e.mt5_request ?? "—"}{e.mt5_retcode != null ? ` (${e.mt5_retcode})` : ""}</td><td className="text-ink-2">{e.reason}</td></tr>))}</tbody></table></div>
        </Section>
      ) : null}

      {d.events.length ? (
        <Section title="Hodisalar">
          <ul className="font-mono text-[11px] text-ink-3">{d.events.map((e, i) => <li key={i}>{timeOnly(e.ts)} · {e.kind}: {e.detail}</li>)}</ul>
        </Section>
      ) : null}
      <button onClick={onClose} className="no-print self-start text-xs text-ink-3 hover:text-ink">Yopish</button>
    </div>
  );
}

export default function SignalsPage() {
  usePageTitle("Signallar");
  const { data, error, loading, reload } = useApi<{ items: Sig[] }>("/api/desk/signals", 10000);
  const [open, setOpen] = useState<string | null>(null);

  const rows = data?.items ?? [];
  const cols: Col<Sig>[] = [
    { key: "id", label: "Signal ID", sort: (r) => r.signal_id, render: (r) => <span className="font-mono text-xs">{r.signal_id}</span> },
    { key: "sym", label: "Symbol", sort: (r) => r.symbol, render: (r) => <span className="font-semibold">{r.symbol}</span> },
    { key: "dir", label: "Direction", sort: (r) => r.direction, render: (r) => <SideBadge side={r.direction} /> },
    { key: "entry", label: "Entry", sort: (r) => r.entry, className: "tabular font-mono text-xs", render: (r) => r.entry ?? "N/A" },
    { key: "sl", label: "Stop Loss", sort: (r) => r.sl, className: "tabular font-mono text-xs", render: (r) => r.sl ?? "N/A" },
    { key: "tp", label: "Take Profit", sort: (r) => r.tp, className: "tabular font-mono text-xs", render: (r) => r.tp ?? "N/A" },
    { key: "rr", label: "R/R", sort: (r) => r.rr, className: "tabular text-xs", render: (r) => num(r.rr) },
    { key: "conf", label: "Confidence", sort: (r) => r.score, render: (r) => <span className="inline-flex items-center gap-1.5"><Badge tone={TIER_TONE[r.tier ?? ""] ?? "mute"}>{r.tier ?? "—"}</Badge><span className="text-xs text-ink-3">{r.score ?? ""}</span></span> },
    { key: "str", label: "Strategy", sort: (r) => r.strategy_id, className: "text-xs text-ink-2", render: (r) => <>{r.strategy_id ?? "N/A"}<div className="text-[10px] text-ink-3">{r.timeframe}</div></> },
    { key: "st", label: "Ijro holati", sort: (r) => r.exec_status ?? r.status, render: (r) => <span className="inline-flex items-center gap-1.5"><Badge tone={EXEC_TONE[r.exec_status ?? ""] ?? STATUS_TONE[r.status] ?? "mute"}>{r.exec_status ?? r.status}</Badge>{r.origin === "forced_test" ? <Badge tone="warn">SINOV</Badge> : null}{r.staff ? <span className={`text-xs ${r.staff.approve ? "text-good" : "text-critical"}`} title={r.staff.reason}>{r.staff.approve ? "✓" : "✕"}</span> : null}</span> },
    { key: "at", label: "Created At", sort: (r) => r.created_at, className: "whitespace-nowrap text-xs text-ink-3", render: (r) => dateTime(r.created_at) },
  ];

  return (
    <>
      <PageHeader title="Signallar" subtitle="Qatorni bosing — to'liq tahlil, xodimlar muhokamasi va (kutilayotgan bo'lsa) HA / YO'Q tugmalari ochiladi." />
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open ?? ""} subtitle="Signal tahlili" width="max-w-2xl">
        {open ? <DetailView key={open} id={open} onClose={() => setOpen(null)} onChanged={reload} /> : null}
      </Drawer>
      <ExecutionFunnel />
      {error ? <ErrorBox error={error} /> : (
        <Card bodyClass="p-0">
          {loading && !data ? <SkeletonRows rows={8} /> : (
            <DataTable rows={rows} cols={cols} rowKey={(r) => r.signal_id} onRow={(r) => setOpen(r.signal_id)}
              search={(r) => `${r.signal_id} ${r.symbol} ${r.strategy_id ?? ""} ${r.status} ${r.exec_status ?? ""}`}
              filters={[
                { label: "Ijro holati", options: Array.from(new Set(rows.map((r) => r.exec_status ?? r.status))), pick: (r) => r.exec_status ?? r.status },
                { label: "Symbol", options: Array.from(new Set(rows.map((r) => r.symbol))), pick: (r) => r.symbol },
                { label: "Daraja", options: Array.from(new Set(rows.map((r) => r.tier ?? ""))).filter(Boolean), pick: (r) => r.tier ?? "" },
              ]}
              empty="Hali signal yo'q." />
          )}
        </Card>
      )}
    </>
  );
}
