"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { IconDownload } from "@/components/icons";
import { Button, Card, ErrorBox, Loading, PageHeader, Pager, SearchInput, Select, StatusChip, Table, Td, Th, Unknown } from "@/components/ui";
import { UNKNOWN_KEY } from "@/lib/constants";
import { bytes, cpuLabel, dateTime, download, toCsv, UNKNOWN } from "@/lib/format";
import { readQuery, useApi, usePageTitle } from "@/lib/hooks";
import type { Device, Source } from "@/lib/types";

const PAGE = 50;

function diskSummary(d: Device): string | null {
  if (!d.disks || !d.disks.length) return null;
  const total = d.disks.reduce((a, x) => a + x.total, 0);
  const free = d.disks.reduce((a, x) => a + x.free, 0);
  return `${bytes(total, 0)} (${bytes(free, 0)} free)`;
}

const matches = (value: string | null, filter: string) =>
  !filter || (filter === UNKNOWN_KEY ? value === null : value === filter);

export default function DevicesPage() {
  usePageTitle("Devices");
  const router = useRouter();
  const [initial] = useState(readQuery);
  const { data, error, loading } = useApi<{ devices: Device[]; sources: Source[]; stale_days: number }>("/api/devices", 60000);
  const [q, setQRaw] = useState(initial.get("q") || "");
  const [org, setOrgRaw] = useState(initial.get("org") || "");
  const [object, setObjectRaw] = useState(initial.get("object") || "");
  const [department, setDepartmentRaw] = useState(initial.get("department") || "");
  const [status, setStatusRaw] = useState(initial.get("status") || "");
  const [source, setSourceRaw] = useState("");
  const [page, setPage] = useState(0);
  const reset = <T,>(fn: (v: T) => void) => (v: T) => { fn(v); setPage(0); };
  const setQ = reset(setQRaw), setOrg = reset(setOrgRaw), setObject = reset(setObjectRaw);
  const setDepartment = reset(setDepartmentRaw), setStatus = reset(setStatusRaw), setSource = reset(setSourceRaw);

  const devices = useMemo(() => data?.devices || [], [data]);
  const options = (key: "organization" | "object" | "department", scope: Device[]) => {
    const names = Array.from(new Set(scope.map((d) => d[key]).filter((x): x is string => !!x))).sort((a, b) => a.localeCompare(b));
    return [{ value: "", label: "All" }, ...names.map((n) => ({ value: n, label: n })), { value: UNKNOWN_KEY, label: UNKNOWN }];
  };
  const orgScope = devices.filter((d) => matches(d.organization, org));
  const objScope = orgScope.filter((d) => matches(d.object, object));
  const sources = useMemo(() => Array.from(new Set(devices.flatMap((d) => d.sources))).sort(), [devices]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    return devices.filter((d) =>
      matches(d.organization, org) && matches(d.object, object) && matches(d.department, department) &&
      (!status || d.status === status) && (!source || d.sources.includes(source)) &&
      (!t || [d.id, d.name, d.os, d.host, d.department, d.object, d.description, ...d.ipv4, ...d.inventory_names]
        .some((x) => (x || "").toLowerCase().includes(t))));
  }, [devices, q, org, object, department, status, source]);

  // Filtrlar URL'da saqlanadi — havolani ulashish / orqaga qaytish ishlaydi.
  useEffect(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (org) p.set("org", org);
    if (object) p.set("object", object);
    if (department) p.set("department", department);
    if (status) p.set("status", status);
    const qs = p.toString();
    window.history.replaceState(null, "", `/devices/${qs ? `?${qs}` : ""}`);
  }, [q, org, object, department, status]);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const rows = filtered.slice(page * PAGE, page * PAGE + PAGE);

  const exportCsv = () => {
    const cols = [
      { key: "id", label: "Device ID" }, { key: "name", label: "Computer name" }, { key: "os", label: "Windows version" },
      { key: "cpu", label: "CPU" }, { key: "ram", label: "RAM" }, { key: "disk", label: "Disk" },
      { key: "status", label: "Last known status" }, { key: "last_seen", label: "Last seen" },
      { key: "organization", label: "Organization" }, { key: "object", label: "Object" },
      { key: "department", label: "Department" }, { key: "last_inventory_update", label: "Last inventory update" },
      { key: "sources", label: "Sources" },
    ];
    const out = filtered.map((d) => ({
      ...d, os: d.os ?? UNKNOWN, cpu: cpuLabel(d.cpu), ram: d.ram_total ? bytes(d.ram_total) : UNKNOWN,
      disk: diskSummary(d) ?? UNKNOWN, organization: d.organization ?? UNKNOWN, object: d.object ?? UNKNOWN,
      department: d.department ?? UNKNOWN, last_seen: d.last_seen ?? UNKNOWN,
      last_inventory_update: d.last_inventory_update ?? UNKNOWN,
    }));
    download(`sentinal-devices-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(out as never, cols));
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Devices"
        subtitle={`${devices.length} registered computer(s). Hardware details are only known for this computer; other values come from AD exports and the agent inventory.`}
        actions={<Button onClick={exportCsv}><IconDownload width={16} height={16} /> Export CSV</Button>} />

      <Card bodyClass="p-0">
        <div className="no-print flex flex-wrap items-end gap-3 border-b border-line px-4 py-3">
          <SearchInput value={q} onChange={setQ} placeholder="Name, ID, IP, OS…" />
          <Select label="Organization" value={org} onChange={(v) => { setOrg(v); setObject(""); setDepartment(""); }} options={options("organization", devices)} />
          <Select label="Object" value={object} onChange={(v) => { setObject(v); setDepartment(""); }} options={options("object", orgScope)} />
          <Select label="Department" value={department} onChange={setDepartment} options={options("department", objScope)} />
          <Select label="Status" value={status} onChange={setStatus} options={[
            { value: "", label: "All" }, { value: "online", label: "Online" }, { value: "active", label: "Active (AD)" },
            { value: "stale", label: `Inactive (AD > ${data?.stale_days ?? 30} days)` }, { value: "disabled", label: "Disabled (AD)" },
            { value: "unknown", label: "Unknown" }]} />
          <Select label="Source" value={source} onChange={setSource} options={[{ value: "", label: "All" }, ...sources.map((s) => ({ value: s, label: s }))]} />
          <span className="ml-auto pb-2 text-xs text-ink-3">{filtered.length} shown</span>
        </div>
        <Table wide>
          <thead>
            <tr>
              <Th>Device ID</Th><Th>Computer name</Th><Th>Windows version</Th><Th>CPU</Th><Th>RAM</Th><Th>Disk</Th>
              <Th>Last known status</Th><Th>Department</Th><Th>Last inventory update</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => {
              const go = () => router.push(`/devices/view/?id=${encodeURIComponent(d.id)}`);
              return (
                <tr key={d.id} onClick={go} onKeyDown={(e) => e.key === "Enter" && go()} tabIndex={0}
                  className="cursor-pointer hover:bg-surface-2/60">
                  <Td className="font-mono text-xs break-all text-ink-2">{d.id}</Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{d.name}</span>
                      {d.is_local ? <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">THIS PC</span> : null}
                    </div>
                    {d.host || d.ipv4.length ? <div className="text-xs text-ink-3">{d.host || d.ipv4.join(", ")}</div> : null}
                  </Td>
                  <Td className="min-w-40"><Unknown value={d.os} /></Td>
                  <Td className="min-w-40 text-ink-2"><Unknown value={d.cpu?.name ? cpuLabel(d.cpu) : null} /></Td>
                  <Td className="tabular whitespace-nowrap text-ink-2"><Unknown value={d.ram_total ? bytes(d.ram_total) : null} /></Td>
                  <Td className="tabular text-ink-2"><Unknown value={diskSummary(d)} /></Td>
                  <Td>
                    <StatusChip status={d.status} title={d.status_detail} />
                    {d.status_detail ? <div className="mt-1 text-xs text-ink-3">{d.status_detail}</div> : null}
                  </Td>
                  <Td className="text-ink-2">
                    <Unknown value={d.department} />
                    {d.object ? <div className="text-xs text-ink-3">{d.object}</div> : null}
                  </Td>
                  <Td className="tabular text-xs text-ink-2"><Unknown value={d.last_inventory_update ? dateTime(d.last_inventory_update) : null} /></Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
        {rows.length === 0 ? <div className="py-10 text-center text-sm text-ink-3">No devices match these filters.</div> : null}
        <Pager page={page} pages={pages} onPage={setPage} total={filtered.length} />
      </Card>
    </div>
  );
}
