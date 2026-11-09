"use client";

import { useEffect, useRef, useState } from "react";
import { Card, Notice, PageHeader } from "@/components/ui";
import { Badge, Drawer, SkeletonRows, useToast } from "@/components/kit";
import { api } from "@/lib/api";
import { ago, timeOnly } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Member { id: string; title: string; unit: string; last_ts: string | null; active: boolean; task?: string | null; counters?: Record<string, number> }
interface PendingSig { signal_id: string; symbol: string; direction: string; status: string; tier: string | null }
interface Msg { id: number; ts: string; role: string; kind: string; text: string; ref: string | null }

const UNIT_LABEL: Record<string, string> = {
  direktor: "Direktor", zona: "Zona skanerlari", yangilik: "Yangiliklar", strategiya: "Strategiya", bahs: "Bahs guruhi", audit: "Audit", xavf: "Xavf", tarix: "Tarix",
};
const KIND_TONE: Record<string, string> = {
  verdict: "border-good/50 bg-good/10", decision: "border-accent/50 bg-accent/10", system: "border-warning/50 bg-warning/10",
  audit: "border-serious/50 bg-serious/10", zone: "border-warning/50 bg-warning/10", owner: "border-accent bg-accent/15", assign: "border-accent/40 bg-accent/5", "task-result": "border-good/40 bg-good/5", "owner-reply": "border-good/60 bg-good/10", report: "border-line bg-surface-2", "zone-talk": "border-accent/40 bg-accent/5",
};

function Avatar({ m, speaking }: { m: Member; speaking: boolean }) {
  return (
    <div className={`relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-line bg-surface-3 font-mono text-[11px] font-semibold ${speaking ? "desk-speaking" : ""}`}>
      {m.id.split("-").map((x) => x[0]).join("")}
      <span className={`absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border border-surface ${m.active ? "bg-good desk-blink" : "bg-ink-3/50"}`} />
    </div>
  );
}

export default function DeskPage() {
  usePageTitle("Xodimlar");
  const staff = useApi<{ members: Member[] }>("/api/desk/staff", 3000);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<Member | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const toast = useToast();
  const sigs = useApi<{ items: PendingSig[] }>("/api/desk/signals", 10000);
  const waiting = (sigs.data?.items ?? []).filter((x) => x.status === "SENT");
  const last = useRef(0);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const r = await api.get<{ items: Msg[] }>(`/api/desk/messages?after=${last.current}`);
        if (stop) return;
        if (r.items.length) {
          last.current = r.items[r.items.length - 1].id;
          setMsgs((prev) => [...prev, ...r.items].slice(-300));
        }
        setErr(null);
      } catch (e) {
        if (!stop) setErr(e instanceof Error ? e.message : String(e));
      }
    };
    tick();
    const id = setInterval(() => { if (document.visibilityState === "visible") tick(); }, 2500);
    return () => { stop = true; clearInterval(id); };
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs.length]);

  async function send() {
    const t = text.trim();
    if (t.length < 2 || sending) return;
    setSending(true);
    try {
      await api.post("/api/desk/command", { cmd: "say", arg: t });
      setText("");
      toast("Topshiriq yuborildi — DIR-1 xodimlarga taqsimlaydi, natija shu chatda.", "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setSending(false);
    }
  }

  const members = staff.data?.members ?? [];
  const byId = Object.fromEntries(members.map((m) => [m.id, m]));
  const speaker = msgs.length ? msgs[msgs.length - 1].role : null;
  const units = Array.from(new Set(members.map((m) => m.unit)));

  return (
    <>
      <Drawer open={!!sel} onClose={() => setSel(null)} title={sel?.id ?? ""} subtitle={sel?.title}>
        {sel ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2"><Badge tone={sel.active ? "good" : "mute"}>{sel.active ? "WORKING" : "kutmoqda"}</Badge><Badge>{UNIT_LABEL[sel.unit] ?? sel.unit}</Badge></div>
            <div className="text-xs text-ink-3">Oxirgi faollik: {sel.last_ts ? `${ago(sel.last_ts)} (${timeOnly(sel.last_ts)})` : "hali xabar yozmagan"}</div>
            <div>
              <div className="mb-2 text-xs font-semibold text-ink-3">Faollik jurnali (yuklangan xabarlar ichidan)</div>
              {msgs.filter((x) => x.role === sel.id).slice(-30).reverse().map((x) => (
                <div key={x.id} className="mb-2 rounded-lg border border-line bg-surface-2 p-3 text-xs">
                  <div className="mb-1 font-mono text-[11px] text-ink-3">{timeOnly(x.ts)} · {x.kind}{x.ref ? ` · ${x.ref}` : ""}</div>
                  <div className="whitespace-pre-wrap break-words text-ink-2">{x.text}</div>
                </div>
              ))}
              {!msgs.some((x) => x.role === sel.id) ? <div className="py-6 text-center text-xs text-ink-3">Bu xodimdan hali xabar yo&apos;q. U faqat signal muhokamasi paytida ishlaydi.</div> : null}
            </div>
          </div>
        ) : null}
      </Drawer>
      <PageHeader title="Trading bo'limi" subtitle="Claude xodimlari: signalni muhokama qiladi, qaror taklif qiladi. Lot, SL va limitlar kodda qoladi — xodimlar ularni o'zgartira olmaydi." />
      {err ? <div className="mb-4"><Notice tone="warn">Bo&apos;lim ma&apos;lumoti o&apos;qilmadi: {err}</Notice></div> : null}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="flex flex-col gap-4 xl:col-span-2">
          {units.map((u) => (
            <Card key={u} title={UNIT_LABEL[u] ?? u} bodyClass="p-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {members.filter((m) => m.unit === u).map((m) => (
                  <button key={m.id} onClick={() => setSel(m)} className={`flex items-center gap-3 rounded-lg border p-2.5 text-left transition-colors hover:border-accent/60 ${speaker === m.id ? "border-accent bg-accent/10" : "border-line bg-surface-2"}`}>
                    <Avatar m={m} speaking={speaker === m.id} />
                    <div className="min-w-0">
                      <div className="truncate font-mono text-xs font-semibold">{m.id}</div>
                      <div className="truncate text-[11px] text-ink-3">{m.title}</div>
                      <div className="line-clamp-2 text-[11px] text-ink-2" title={m.task ?? ""}>{m.task ?? "hali ish yo'q"}</div>
                      <div className="text-[11px] text-ink-3">{m.active ? "WORKING" : m.last_ts ? `ONLINE · oxirgi ${ago(m.last_ts)}` : "kutmoqda (hali faol bo'lmagan)"}</div>
                    </div>
                  </button>
                ))}
              </div>
            </Card>
          ))}
          {staff.loading && !staff.data ? <Card><SkeletonRows rows={6} /></Card> : null}
        </div>
        <div className="flex flex-col gap-4 xl:col-span-3">
        {waiting.length ? (
          <Card title="Tasdiq kutayotgan vazifalar" subtitle="Holati SENT: egasi tugmasi yoki 'Jamoaga' kutmoqda" bodyClass="p-3">
            <div className="flex flex-wrap gap-2">{waiting.map((w) => <a key={w.signal_id} href="/signals/" className="rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-xs hover:border-accent/60"><span className="font-mono">{w.signal_id}</span> · {w.symbol} {w.direction} · {w.tier}</a>)}</div>
          </Card>
        ) : null}
        <Card title="Discussion Room" subtitle="Yangi xabarlar 2.5 soniyada keladi" bodyClass="p-0">
          <div className="flex max-h-[70vh] min-h-[420px] flex-col gap-2 overflow-y-auto p-4">
            {msgs.length === 0 ? <div className="m-auto text-sm text-ink-3">Hali muhokama bo&apos;lmagan. Signal chiqqanda yoki &quot;Signallar&quot; sahifasidan topshirilganda shu yerda ko&apos;rinadi.</div> : null}
            {msgs.map((m, i) => {
              const showRef = m.ref && (i === 0 || msgs[i - 1].ref !== m.ref);
              return (
                <div key={m.id}>
                  {showRef ? <div className="my-2 border-t border-line pt-2 font-mono text-[11px] text-ink-3">— {m.ref} —</div> : null}
                  <div className={`desk-in flex gap-3 rounded-lg border p-3 ${KIND_TONE[m.kind] ?? "border-line bg-surface-2"}`}>
                    <div className="w-24 shrink-0">
                      <div className="font-mono text-xs font-semibold">{m.role}</div>
                      <div className="text-[10px] text-ink-3">{byId[m.role]?.title ?? ""}</div>
                      <div className="text-[10px] text-ink-3">{timeOnly(m.ts)}</div>
                    </div>
                    <div className="min-w-0 whitespace-pre-wrap break-words text-sm text-ink-2">{m.text}</div>
                  </div>
                </div>
              );
            })}
            <div ref={endRef} />
          </div>
          <form className="no-print flex gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={500} rows={2} aria-label="Xodimlarga topshiriq"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Xodimlarga topshiriq yoki savol yozing (masalan: BTC va ETH aktiv zonalarini tekshirib, xavfini baholang). Enter — yuborish."
              className="min-h-[44px] flex-1 resize-none rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-3" />
            <button type="submit" disabled={sending || text.trim().length < 2} className="self-end rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">Yuborish</button>
          </form>
        </Card>
        </div>
      </div>
    </>
  );
}
