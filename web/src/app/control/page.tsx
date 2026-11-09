"use client";

import { useState } from "react";
import { Button, Card, ErrorBox, Loading, Notice, PageHeader, StatusChip, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Cmd { id: number; ts: string; cmd: string; arg: string | null; status: string; result: string | null }
interface State { settings: Record<string, unknown>; commands: Cmd[]; balance: { balance: number; ts: string } | null }

const MODE_INFO: Record<string, string> = {
  analysis: "Faqat kuzatish: signal yuborilmaydi.",
  confirm: "Signal chatga keladi, zdelka faqat HA tugmasi bilan.",
  auto: "Kuchli signal: xodimlar bahsi -> himoyalar -> DEMO zdelka (tugmasiz).",
};

export default function ControlPage() {
  usePageTitle("Boshqaruv");
  const { data, error, loading, reload } = useApi<State>("/api/desk/control", 3000);
  const [note, setNote] = useState<string | null>(null);
  const s = data?.settings ?? {};
  const mode = s.mode === "dry" ? "analysis" : s.trade_mode === "auto" ? "auto" : "confirm";

  async function send(cmd: string, arg: string, ask: string) {
    if (!window.confirm(ask)) return;
    try {
      const r = await api.post<{ id: number }>("/api/desk/command", { cmd, arg });
      setNote(`Buyruq #${r.id} qabul qilindi — agent bir necha soniyada bajaradi (natija pastdagi jadvalda).`);
      reload();
    } catch (e) { setNote(e instanceof Error ? e.message : String(e)); }
  }

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <>
      <PageHeader title="Boshqaruv" subtitle="Hamma buyruq agentga navbat orqali boradi; himoyalar (lot, SL, limitlar, o'chirgich) agentning o'zida tekshiriladi. Faqat MT5 DEMO." />
      {note ? <div className="mb-4"><Notice>{note}</Notice></div> : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Savdo rejimi" subtitle={`Hozir: ${mode.toUpperCase()}`}>
          <div className="flex flex-wrap gap-2">
            {(["analysis", "confirm", "auto"] as const).map((m) => (
              <Button key={m} variant={mode === m ? "primary" : "secondary"} disabled={mode === m}
                onClick={() => send("mode", m, m === "auto" ? "AUTO yoqilsinmi? Agent kuchli signalda DEMO hisobda o'zi zdelka ochadi (minimal lot, risk chegarasi bilan)." : `${m.toUpperCase()} rejimiga o'tilsinmi?`)}>
                {m.toUpperCase()}
              </Button>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-3">{MODE_INFO[mode]}</p>
        </Card>
        <Card title="Favqulodda" subtitle="Tasdiq so'raladi">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => send("stop", "", "AUTO to'xtatilsinmi? (ochiq pozitsiyalar joyida qoladi)")}>AUTO to&apos;xtatish</Button>
            <Button variant="primary" onClick={() => send("flat", "", "Agent ochgan HAMMA demo pozitsiyalar yopilsinmi?")}>Hammasini yopish</Button>
          </div>
          <div className="mt-4 border-t border-line pt-4">
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => send("zone", "", "DIR-1 zona vazifasi hozir bir marta ishga tushsinmi? Aktiv zonadan signal tuziladi, xodimlar bahsi va hamma himoyadan o'tsa MT5 DEMO'da zdelka ochiladi.")}>Zona zdelkasini hozir sinash (DEMO)</Button>
              <Button variant="primary" onClick={() => send("zone", "force", "MAJBURIY SINOV: DIR-1 bahssiz va kuldaunsiz BITTA zdelka ochishga urinadi (eng mos nomzod). Lot, SL, R/R>=1.5, spred, kunlik zarar, korrelyatsiya va faqat-DEMO himoyalari baribir tekshiriladi. Davom etasizmi?")}>Majburiy sinov (bahssiz, 1 zdelka)</Button>
              <Button variant="secondary" onClick={() => send("zone", "test", "SINOV: TP qarshi zonaga emas, 2R ga qo'yiladi (bahs, lot, SL, R/R>=1.5 va boshqa himoyalar baribir tekshiriladi). Faqat DEMO. Davom etasizmi?")}>Sinov rejimi (TP=2R)</Button>
            </div>
            <p className="mt-2 text-xs text-ink-3">Faqat AUTO rejimda. Bahs va himoyalar baribir tekshiriladi; REAL hisobda hech qachon.</p>
          </div>
          <p className="mt-3 text-xs text-ink-3">Yopish faqat SENTINAL ochgan (magic) pozitsiyalarga tegadi; qo&apos;lda/EA ochganlariga tegmaydi.</p>
        </Card>
        <Card title="Joriy sozlamalar" className="lg:col-span-2" bodyClass="p-0">
          <Table><tbody>{Object.entries(s).map(([k, v]) => (<tr key={k}><Td className="font-mono text-xs text-ink-3">{k}</Td><Td className="font-mono text-xs">{String(v)}</Td></tr>))}</tbody></Table>
          <p className="px-4 py-3 text-xs text-ink-3">Sozlamalarni o&apos;zgartirish: Telegramda /trading_mode yoki agentga yozing (xavfsiz, tasdiq bilan).</p>
        </Card>
        <Card title="Buyruqlar tarixi" className="lg:col-span-2" bodyClass="p-0">
          <Table wide>
            <thead><tr><Th>#</Th><Th>Vaqt</Th><Th>Buyruq</Th><Th>Holat</Th><Th>Natija</Th></tr></thead>
            <tbody>{(data?.commands ?? []).map((c) => (
              <tr key={c.id}><Td>{c.id}</Td><Td className="text-xs text-ink-3">{dateTime(c.ts)}</Td><Td className="font-mono text-xs">{c.cmd} {c.arg}</Td>
                <Td><StatusChip status={c.status === "done" ? "ok" : c.status === "failed" ? "failed" : "running"} /></Td><Td className="text-xs">{c.result}</Td></tr>))}
            </tbody>
          </Table>
        </Card>
      </div>
    </>
  );
}
