"use client";

import Link from "next/link";
import { Meter } from "@/components/charts";
import { Card, Empty, ErrorBox, Field, Loading, Notice, PageHeader, StatusChip, Table, Td, Th, Unknown } from "@/components/ui";
import { bytes, cpuLabel, dateTime, duration } from "@/lib/format";
import { useApi, usePageTitle, useQuery } from "@/lib/hooks";
import type { Action, Device, LocalSystem, Metrics, Task } from "@/lib/types";

interface Detail {
  device: Device;
  actions: Action[];
  tasks: Task[];
  activity_window_days: number;
  local?: LocalSystem;
  metrics?: Metrics;
}

export default function DeviceDetailPage() {
  const query = useQuery();
  const id = query?.get("id") || null;
  const { data, error, loading } = useApi<Detail>(id ? `/api/devices/${encodeURIComponent(id)}` : null, 10000);
  usePageTitle(data?.device.name || "Device");

  if (query && !id) return <ErrorBox error="No device selected." />;
  if ((loading || !query) && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;

  const d = data.device;
  const m = data.metrics;
  const sys = d.system || {};

  return (
    <div className="flex flex-col gap-6">
      <div className="text-xs text-ink-3">
        <Link href="/devices/" className="hover:text-ink">Devices</Link> <span className="px-1">/</span> {d.name}
      </div>
      <PageHeader title={d.name}
        subtitle={<span className="flex flex-wrap items-center gap-2"><StatusChip status={d.status} />{d.status_detail}</span>} />

      {d.is_local && m ? (
        <Card title="Live utilization" subtitle="Read-only, collected on this computer every few seconds"
          actions={<Link href="/monitoring/" className="text-xs text-accent hover:underline">Full monitoring</Link>}>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            <Meter label="CPU" value={m.cpu} />
            <Meter label="Memory" value={m.ram} detail={`${bytes(m.ram_used)} of ${bytes(m.ram_total)}`} />
            <Meter label={`System disk ${m.disk_mount || ""}`} value={m.disk} />
          </div>
        </Card>
      ) : null}

      {!d.is_local ? (
        <Notice>
          Hardware (CPU, RAM, disks) is shown only for this computer. For other devices the dashboard has no data
          source and does not connect to them, so those fields read <b>Unknown</b>.
        </Notice>
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Identity">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Device ID"><span className="font-mono text-xs">{d.id}</span></Field>
            <Field label="Computer name">{d.name}</Field>
            <Field label="Type"><Unknown value={d.type} /></Field>
            <Field label="Host"><Unknown value={d.host} mono /></Field>
            <Field label="IPv4 addresses"><Unknown value={d.ipv4.length ? d.ipv4.join(", ") : null} mono /></Field>
            <Field label="Domain"><Unknown value={d.domain} /></Field>
            <Field label="Last seen"><Unknown value={d.last_seen ? dateTime(d.last_seen) : null} /></Field>
            <Field label="Last inventory update"><Unknown value={d.last_inventory_update ? dateTime(d.last_inventory_update) : null} /></Field>
            <Field label="Description"><Unknown value={d.description} /></Field>
            <Field label="Agent inventory name"><Unknown value={d.inventory_names.length ? d.inventory_names.join(", ") : null} /></Field>
          </dl>
        </Card>

        <Card title="Organization">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Organization"><Unknown value={d.organization} /></Field>
            <Field label="Object"><Unknown value={d.object} /></Field>
            <Field label="Department"><Unknown value={d.department} /></Field>
            <Field label="Hierarchy source"><Unknown value={d.hierarchy_source} /></Field>
            <Field label="AD OU path"><Unknown value={d.ou_path.length ? d.ou_path.join(" / ") : null} /></Field>
            <Field label="Data sources">{d.sources.join(", ")}</Field>
          </dl>
        </Card>

        <Card title="Operating system & hardware">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Windows version"><Unknown value={d.os} /></Field>
            <Field label="Build"><Unknown value={d.os_version} /></Field>
            <Field label="CPU"><Unknown value={d.cpu?.name ? cpuLabel(d.cpu) : null} /></Field>
            <Field label="RAM"><Unknown value={d.ram_total ? bytes(d.ram_total) : null} /></Field>
            <Field label="Manufacturer / model"><Unknown value={[sys.manufacturer, sys.model].filter(Boolean).join(" ") || null} /></Field>
            <Field label="BIOS"><Unknown value={sys.bios ? `${sys.bios}${sys.bios_date ? ` (${sys.bios_date})` : ""}` : null} /></Field>
            {data.local ? <Field label="Windows installed"><Unknown value={data.local.windows.installed ? dateTime(data.local.windows.installed) : null} /></Field> : null}
            {data.local ? <Field label="Installed software"><Link href="/monitoring/#software" className="text-accent hover:underline">{d.software_count} application(s)</Link></Field> : null}
            {m ? <Field label="Uptime">{duration(m.uptime_sec)}</Field> : null}
          </dl>
        </Card>

        <Card title="Disks" bodyClass="p-0">
          {d.disks && d.disks.length ? (
            <Table>
              <thead><tr><Th>Volume</Th><Th>File system</Th><Th className="text-right">Size</Th><Th className="text-right">Free</Th><Th className="w-48">Used</Th></tr></thead>
              <tbody>
                {d.disks.map((x) => (
                  <tr key={x.mount}>
                    <Td className="font-mono text-xs">{x.mount}</Td>
                    <Td className="text-ink-2">{x.fstype} · {x.kind}</Td>
                    <Td className="tabular text-right">{bytes(x.total)}</Td>
                    <Td className="tabular text-right">{bytes(x.free)}</Td>
                    <Td><Meter label="" value={x.percent} /></Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : <Empty>Unknown — no disk data source for this device.</Empty>}
        </Card>
      </div>

      <Card title="SENTINAL AI activity on this device" subtitle={`Last ${data.activity_window_days} days, matched by name, host or IP in the agent journal`} bodyClass="p-0">
        {data.tasks.length === 0 ? <Empty>No agent tasks touched this device in the last {data.activity_window_days} days.</Empty> : (
          <Table>
            <thead><tr><Th>Timestamp</Th><Th>Task</Th><Th>Result</Th><Th>Error</Th></tr></thead>
            <tbody>
              {data.tasks.map((t) => (
                <tr key={t.id}>
                  <Td className="tabular whitespace-nowrap text-xs text-ink-2">{dateTime(t.ts)}</Td>
                  <Td className="max-w-xl"><div className="line-clamp-2">{t.description || "—"}</div><div className="text-xs text-ink-3">{t.id} · {t.actions} action(s)</div></Td>
                  <Td><StatusChip status={t.status} /></Td>
                  <Td className="max-w-md text-xs text-ink-2">{t.error || (t.failed_actions ? `${t.failed_actions} failed action(s)` : "—")}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
