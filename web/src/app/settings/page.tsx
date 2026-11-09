"use client";

import Link from "next/link";
import { Card, ErrorBox, Notice, PageHeader } from "@/components/ui";
import { Badge, SkeletonRows } from "@/components/kit";
import { useApi, usePageTitle } from "@/lib/hooks";

const HELP: Record<string, string> = {
  mode: "live = signallar chatga yuboriladi; dry = faqat kuzatish", trade_mode: "confirm = tugma bilan; auto = agent o'zi (faqat DEMO)",
  demo_orders: "MT5 DEMO buyurtmalari ruxsat", sizing: "risk = 1% risk bo'yicha lot", risk_pct: "Bir zdelka riski, % balans",
  split: "TP1/TP2 bo'lib yopish", max_groups: "Bir vaqtda maksimum zdelka guruhi", time_stop_h: "Vaqt bo'yicha yopish (soat)",
  min_lot_fallback: "Kichik balansda minimal lot bilan kirish", min_lot_max_risk_pct: "Shunda ruxsat etilgan eng katta risk, %",
  staff_gate: "AUTO'da xodimlar bahsi shart", breaker_losses: "Ketma-ket zarar — o'chirgich", breaker_dd_pct: "Drawdown — o'chirgich, %",
  auto_min_tier: "AUTO uchun minimal daraja", daily_loss_pct: "Kunlik maksimal zarar, %", target: "Maqsad",
};

export default function SettingsPage() {
  usePageTitle("Sozlamalar");
  const { data, error, loading } = useApi<{ settings: Record<string, unknown> }>("/api/desk/control", 10000);
  return (
    <>
      <PageHeader title="Sozlamalar" subtitle="Trading sozlamalari (faqat o'qish). Xavf limitlari veb orqali o'zgartirilmaydi." />
      <div className="mb-4"><Notice>Rejimni o&apos;zgartirish uchun <Link href="/control/" className="text-accent underline">Boshqaruv</Link> sahifasidan foydalaning. Xavf parametrlari (risk, limitlar, o&apos;chirgich) faqat konfig fayl yoki Telegram orqali, tasdiq bilan o&apos;zgaradi.</Notice></div>
      {error ? <ErrorBox error={error} /> : (
        <Card bodyClass="p-0">
          {loading && !data ? <SkeletonRows rows={8} /> : (
            <table className="w-full text-sm"><tbody>{Object.entries(data?.settings ?? {}).map(([k, v]) => (
              <tr key={k} className="border-b border-line/50 hover:bg-surface-2">
                <td className="px-5 py-2.5 font-mono text-xs text-ink-3">{k}</td>
                <td className="px-3"><Badge tone={v === true ? "good" : v === false ? "mute" : "info"}>{String(v)}</Badge></td>
                <td className="px-5 text-xs text-ink-3">{HELP[k] ?? ""}</td>
              </tr>))}</tbody></table>
          )}
        </Card>
      )}
    </>
  );
}
