"use client";

import { useMemo, useState } from "react";
import { Legend, LineChart, Meter, TableView } from "@/components/charts";
import { IconRefresh } from "@/components/icons";
import { Button, Card, ErrorBox, Field, Loading, Notice, PageHeader, SearchInput, StatTile, Table, Td, Th, Unknown } from "@/components/ui";
import { api } from "@/lib/api";
import { bytes, cpuLabel, dateTime, duration, rate, timeOnly } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";
import type { HistoryPoint, LocalSystem, Metrics, Software } from "@/lib/types";

export default function MonitoringPage() {
  usePageTitle("Monitoring");
  const live = useApi<Metrics>("/api/monitoring/current", 3000);
  const hist = useApi<{ interval: number; points: HistoryPoint[] }>("/api/monitoring/history", 5000);
  const sys = useApi<LocalSystem>("/api/monitoring/system");
  const sw = useApi<{ collected_at: string; count: number; software: Software[] }>("/api/monitoring/software");
  const [q, setQ] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);

  const points = useMemo(() => hist.data?.points || [], [hist.data]);
  const labels = points.map((p) => p.ts);
  const software = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = sw.data?.software || [];
    return t ? list.filter((s) => [s.name, s.publisher, s.version].some((x) => (x || "").toLowerCase().includes(t))) : list;
  }, [sw.data, q]);

  async function refresh() {
    setRefreshing(true);
    setRefreshMsg(null);
    try {
      const r = await api.post<{ collected_at: string; software_count: number }>("/api/monitoring/refresh");
      setRefreshMsg(`Inventory refreshed at ${timeOnly(r.collected_at)} · ${r.software_count} applications`);
      await Promise.all([sys.reload(), sw.reload()]);
    } catch (e) {
      setRefreshMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }

  if (live.loading && !live.data) return <Loading />;
  if (live.error && !live.data) return <ErrorBox error={live.error} />;
  const m = live.data as Metrics;
  const s = sys.data;
  const ramUsedPct = m.ram;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Monitoring"
        subtitle={<>Read-only monitoring of <b className="text-ink-2">this computer only</b> ({s?.computer_name || "…"}), using psutil and the Windows registry. No network scanning, no other computers.</>}
        actions={<Button onClick={refresh} disabled={refreshing}><IconRefresh width={16} height={16} className={refreshing ? "animate-spin" : ""} /> {refreshing ? "Collecting…" : "Refresh inventory"}</Button>} />
      {refreshMsg ? <Notice>{refreshMsg}</Notice> : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="CPU utilization" value={`${m.cpu.toFixed(0)}%`} sub={`${m.cpu_per_core.length} logical cores · updated ${timeOnly(m.ts)}`} />
        <StatTile label="Memory utilization" value={`${ramUsedPct.toFixed(0)}%`} sub={`${bytes(m.ram_used)} of ${bytes(m.ram_total)} · page file ${m.swap.toFixed(0)}%`} />
        <StatTile label={`System disk ${m.disk_mount || ""}`} value={m.disk === null ? "Unknown" : `${m.disk.toFixed(0)}%`}
          sub={(() => { const d = m.disks.find((x) => x.mount === m.disk_mount); return d ? `${bytes(d.free)} free of ${bytes(d.total)}` : "Unknown"; })()} />
        <StatTile label="Uptime" value={duration(m.uptime_sec)} sub={s ? `Booted ${dateTime(s.boot_time)}` : ""} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="CPU and memory" subtitle={`Last ${Math.round((points.length * (hist.data?.interval || 5)) / 60)} min, sampled every ${hist.data?.interval || 5} s (kept in memory since the dashboard started)`}
          actions={<Legend items={[{ name: "CPU", color: "var(--series-1)", marker: "line" }, { name: "Memory", color: "var(--series-2)", marker: "line" }]} />}>
          <LineChart ariaLabel="CPU and memory utilization over time, percent" labels={labels} yMax={100} format={(v) => `${v.toFixed(0)}%`}
            series={[{ name: "CPU", color: "var(--series-1)", values: points.map((p) => p.cpu) },
              { name: "Memory", color: "var(--series-2)", values: points.map((p) => p.ram) }]} />
          <TableView columns={[{ key: "t", label: "Time" }, { key: "cpu", label: "CPU %" }, { key: "ram", label: "Memory %" }]}
            rows={points.slice(-60).reverse().map((p) => ({ t: p.ts.replace("T", " "), cpu: p.cpu, ram: p.ram }))} />
        </Card>
        <Card title="Disk activity" subtitle={`Read / write throughput (all disks) · now ${rate(m.disk_read_bps)} read, ${rate(m.disk_write_bps)} write`}
          actions={<Legend items={[{ name: "Read", color: "var(--series-3)", marker: "line" }, { name: "Write", color: "var(--series-4)", marker: "line" }]} />}>
          <LineChart ariaLabel="Disk read and write throughput over time" labels={labels} format={(v) => rate(v).replace(".0 ", " ")}
            series={[{ name: "Read", color: "var(--series-3)", values: points.map((p) => p.disk_read_bps) },
              { name: "Write", color: "var(--series-4)", values: points.map((p) => p.disk_write_bps) }]} />
          <TableView columns={[{ key: "t", label: "Time" }, { key: "r", label: "Read" }, { key: "w", label: "Write" }]}
            rows={points.slice(-60).reverse().map((p) => ({ t: p.ts.replace("T", " "), r: rate(p.disk_read_bps), w: rate(p.disk_write_bps) }))} />
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Disk utilization" subtitle="Space used per volume">
          <div className="flex flex-col gap-5">
            {m.disks.map((d) => (
              <Meter key={d.mount} label={`${d.mount} · ${d.fstype}${d.kind === "removable" ? " · removable" : ""}`} value={d.percent}
                detail={`${bytes(d.used)} used · ${bytes(d.free)} free · ${bytes(d.total)} total`} />
            ))}
          </div>
        </Card>
        <Card title="CPU per logical core" subtitle="Current utilization">
          <div className="grid grid-cols-2 gap-x-6 gap-y-4">
            {m.cpu_per_core.map((v, i) => <Meter key={i} label={`Core ${i}`} value={v} />)}
          </div>
        </Card>
        <Card title="System">
          {s ? (
            <dl className="grid grid-cols-1 gap-4">
              <Field label="Windows version"><Unknown value={s.windows.label} /></Field>
              <Field label="Edition · architecture"><Unknown value={[s.windows.edition, s.windows.architecture].filter(Boolean).join(" · ") || null} /></Field>
              <Field label="Windows installed"><Unknown value={s.windows.installed ? dateTime(s.windows.installed) : null} /></Field>
              <Field label="CPU"><Unknown value={s.cpu.name ? `${cpuLabel(s.cpu)}${s.cpu.mhz ? ` · ${s.cpu.mhz} MHz` : ""}` : null} /></Field>
              <Field label="RAM"><Unknown value={s.ram_total ? bytes(s.ram_total) : null} /></Field>
              <Field label="Manufacturer / model"><Unknown value={[s.system.manufacturer, s.system.model].filter(Boolean).join(" ") || null} /></Field>
              <Field label="Domain"><Unknown value={s.domain} /></Field>
              <Field label="IPv4"><Unknown value={s.ipv4.length ? s.ipv4.map((a) => `${a.address} (${a.interface})`).join(", ") : null} /></Field>
              <Field label="Inventory collected"><Unknown value={dateTime(s.collected_at)} /></Field>
            </dl>
          ) : sys.error ? <ErrorBox error={sys.error} /> : <Loading />}
        </Card>
      </div>

      <div id="software">
        <Card title="Installed software" bodyClass="p-0"
          subtitle={sw.data ? `${sw.data.count} application(s) from the Windows "Programs and Features" registry keys · collected ${dateTime(sw.data.collected_at)}` : "Loading…"}
          actions={<SearchInput value={q} onChange={setQ} placeholder="Name, publisher, version" />}>
          {sw.error ? <div className="p-4"><ErrorBox error={sw.error} /></div> : (
            <div className="max-h-[560px] overflow-auto">
              <Table wide>
                <thead><tr><Th>Name</Th><Th>Version</Th><Th>Publisher</Th><Th>Installed</Th><Th className="text-right">Size</Th><Th>Scope</Th></tr></thead>
                <tbody>
                  {software.map((x) => (
                    <tr key={`${x.name}|${x.version}`} className="hover:bg-surface-2/60">
                      <Td className="max-w-md">{x.name}</Td>
                      <Td className="font-mono text-xs text-ink-2"><Unknown value={x.version} /></Td>
                      <Td className="max-w-xs text-ink-2"><Unknown value={x.publisher} /></Td>
                      <Td className="tabular text-xs text-ink-2"><Unknown value={x.installed} /></Td>
                      <Td className="tabular text-right text-xs text-ink-2"><Unknown value={x.size_mb ? `${x.size_mb.toLocaleString("en-US")} MB` : null} /></Td>
                      <Td className="text-xs text-ink-3">{x.scope}{x.arch ? ` · ${x.arch}` : ""}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              {software.length === 0 ? <div className="py-8 text-center text-sm text-ink-3">No matching applications.</div> : null}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
