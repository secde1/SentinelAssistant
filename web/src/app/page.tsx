"use client";

import Link from "next/link";
import { BarList, Meter, SegmentedBar, Sparkline } from "@/components/charts";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatTile, StatusChip, Unknown } from "@/components/ui";
import { ago, bytes, dateTime, duration, timeOnly } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";
import { STATUS_PARTS, topWithOther } from "@/lib/constants";
import type { HistoryPoint, Metrics, Overview } from "@/lib/types";

export default function DashboardPage() {
  usePageTitle("Dashboard");
  const { data, error, loading } = useApi<Overview>("/api/overview", 15000);
  const live = useApi<Metrics>("/api/monitoring/current", 5000);
  const hist = useApi<{ points: HistoryPoint[] }>("/api/monitoring/history", 15000);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;

  const m = live.data || data.metrics;
  const points = hist.data?.points || [];
  const st = data.device_status;
  const agent = data.agent;
  const ctl = agent.control;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Dashboard"
        subtitle="Device inventory, this computer's health and SENTINAL AI activity — read-only." />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Registered devices" value={data.devices_total.toLocaleString("en-US")} href="/devices/"
          sub={<>{(st.active || 0) + (st.online || 0)} active · {st.stale || 0} inactive · {st.disabled || 0} disabled</>} />
        <StatTile label="Organizations · objects · departments" href="/organizations/"
          value={<span>{data.organizations}<span className="text-ink-3"> · </span>{data.objects}<span className="text-ink-3"> · </span>{data.departments}</span>}
          sub={data.unassigned ? <>{data.unassigned} device(s) without hierarchy data</> : "All devices assigned"} />
        <StatTile label="Agent tasks today" value={data.today.tasks} href="/activity/"
          sub={<>{data.today.ok} succeeded · {data.today.failed} failed · {data.today.actions} actions</>} />
        <StatTile label="SENTINAL AI agent" href="/settings/"
          value={<span className="text-2xl">{agent.running ? (ctl?.busy ? "Working" : "Online") : "Offline"}</span>}
          accent={<span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: agent.running ? "var(--good)" : "var(--ink-3)" }} />}
          sub={agent.running
            ? <>{ctl?.model || "model ?"}{ctl?.limits ? ` · ${ctl.limits}` : ""}</>
            : agent.stopped_by_owner ? "Stopped by owner (agentctl start)" : `Last heartbeat ${ago(agent.last_alive)}`} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={<>This computer · {data.local.name || "Unknown"}</>}
          subtitle={<Unknown value={data.local.os} />}
          actions={<Link href="/monitoring/" className="text-xs text-accent hover:underline">Open monitoring</Link>}>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            <div>
              <Meter label="CPU" value={m.cpu} detail={`${m.cpu_per_core?.length || "?"} logical cores`} />
              <div className="mt-3"><Sparkline values={points.map((p) => p.cpu)} /></div>
            </div>
            <div>
              <Meter label="Memory" value={m.ram} detail={`${bytes(m.ram_used)} of ${bytes(m.ram_total)}`} />
              <div className="mt-3"><Sparkline values={points.map((p) => p.ram)} /></div>
            </div>
            <div>
              <Meter label={`System disk ${m.disk_mount || ""}`} value={m.disk}
                detail={(() => {
                  const d = m.disks?.find((x) => x.mount === m.disk_mount);
                  return d ? `${bytes(d.free)} free of ${bytes(d.total)}` : "Unknown";
                })()} />
              <div className="mt-3 text-xs text-ink-3">Uptime {duration(m.uptime_sec)} · updated {timeOnly(m.ts)}</div>
            </div>
          </div>
        </Card>

        <Card title="Device status" subtitle="From AD exports, agent inventory and this computer">
          <SegmentedBar parts={STATUS_PARTS.map((p) => ({ name: p.name, value: st[p.key] || 0, color: p.color }))} />
          <p className="mt-4 text-xs leading-relaxed text-ink-3">
            “Inactive” means no AD logon in the configured window. Devices only known from the agent inventory have an
            unknown status — nothing is pinged or scanned.
          </p>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Windows versions" subtitle="Top operating systems across all devices">
          <BarList items={topWithOther(data.os, 6)} hrefFor={(n) => n === "Other" ? null : `/devices/?q=${encodeURIComponent(n === "Unknown" ? "" : n)}`} />
        </Card>
        <Card className="xl:col-span-2" title="Recent agent activity" subtitle="Today's tasks from the SENTINAL AI journal"
          actions={<Link href="/activity/" className="text-xs text-accent hover:underline">Activity history</Link>}
          bodyClass="p-0">
          {data.today.recent.length === 0 ? <Empty>No agent tasks recorded today.</Empty> : (
            <ul className="divide-y divide-line/60">
              {data.today.recent.map((t) => (
                <li key={t.id} className="flex items-start gap-3 px-5 py-3">
                  <span className="tabular w-12 shrink-0 pt-0.5 text-xs text-ink-3">{timeOnly(t.ts)}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm" title={t.description || ""}>{t.description || <span className="text-ink-3">No description</span>}</div>
                    <div className="mt-0.5 text-xs text-ink-3">
                      {t.id} · {t.devices.length ? t.devices.join(", ") : "no device actions"} · {t.actions} action(s)
                    </div>
                  </div>
                  <StatusChip status={t.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Data sources" subtitle="Where the dashboard reads its data from (nothing is fabricated: missing values show as Unknown)"
        bodyClass="p-0">
        <ul className="divide-y divide-line/60">
          {data.sources.map((s) => (
            <li key={s.label + s.path} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-2.5 text-sm">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.exists && !s.error ? "var(--good)" : "var(--ink-3)" }} />
              <span className="min-w-56">{s.label}</span>
              <span className="text-xs text-ink-3">{s.exists ? `${s.records} record(s)` : "not present"}</span>
              <span className="text-xs text-ink-3">{s.updated ? `updated ${dateTime(s.updated)}` : ""}</span>
              {s.error ? <span className="text-xs text-critical">{s.error}</span> : null}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
