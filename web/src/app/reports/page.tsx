"use client";

import { useState } from "react";
import { BarList, Legend, SegmentedBar, StackedColumns, TableView } from "@/components/charts";
import { IconDownload, IconPrint } from "@/components/icons";
import { Button, Card, ErrorBox, Loading, PageHeader, StatTile, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { STATUS_PARTS, topWithOther } from "@/lib/constants";
import { dateTime, download, toCsv } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";
import type { Report, Task } from "@/lib/types";

function isoDay(d: Date) {
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const STATUS_KEY: Record<string, string> = {
  "online": "online", "active": "active", "stale": "stale", "disabled": "disabled", "unknown": "unknown", "Unknown": "unknown",
};

export default function ReportsPage() {
  usePageTitle("Reports");
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (Number(days) - 1));
  const range = `start=${isoDay(start)}&end=${isoDay(end)}`;
  const { data, error, loading } = useApi<Report>(`/api/reports?${range}`);
  const [exporting, setExporting] = useState(false);

  async function exportTasks() {
    setExporting(true);
    try {
      const r = await api.get<{ items: Task[] }>(`/api/activity?view=tasks&${range}&limit=1000`);
      download(`sentinal-tasks-${isoDay(start)}_${isoDay(end)}.csv`, toCsv(r.items as never, [
        { key: "ts", label: "Timestamp" }, { key: "id", label: "Task" }, { key: "devices", label: "Device" },
        { key: "description", label: "Task description" }, { key: "status", label: "Execution result" },
        { key: "error", label: "Error information" }, { key: "actions", label: "Actions" }, { key: "failed_actions", label: "Failed actions" },
      ]));
    } finally {
      setExporting(false);
    }
  }

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;

  const inv = data.inventory;
  const statusParts = STATUS_PARTS.map((p) => ({
    name: p.name, color: p.color,
    value: inv.by_status.filter((s) => STATUS_KEY[s.name] === p.key).reduce((a, s) => a + s.count, 0),
  }));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Reports"
        subtitle={<>SENTINAL AI activity {data.range.start} — {data.range.end} and the current device inventory. Generated {dateTime(new Date().toISOString())}.</>}
        actions={<>
          <Tabs value={days} onChange={setDays} items={[{ value: "7", label: "7 days" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }]} />
          <Button onClick={exportTasks} disabled={exporting}><IconDownload width={16} height={16} /> Tasks CSV</Button>
          <Button onClick={() => download(`sentinal-report-${data.range.start}_${data.range.end}.json`, JSON.stringify(data, null, 2), "application/json")}>
            <IconDownload width={16} height={16} /> Report JSON</Button>
          <Button onClick={() => window.print()}><IconPrint width={16} height={16} /> Print</Button>
        </>} />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Tasks" value={data.tasks_total} sub={`${data.tasks_ok} succeeded · ${data.tasks_failed} not successful`} />
        <StatTile label="Success rate" value={data.success_rate === null ? "—" : `${data.success_rate}%`} sub="of finished tasks" />
        <StatTile label="Actions" value={data.actions_total} sub={`${data.actions_failed} failed${data.avg_action_ms ? ` · avg ${(data.avg_action_ms / 1000).toFixed(1)} s` : ""}`} />
        <StatTile label="Changes made" value={data.changes_made} sub={`${data.changes_verified} verified afterwards`} />
        <StatTile label="Agent restarts" value={data.agent_restarts} sub={`${data.agent_crashes} crash(es)`} />
        <StatTile label="Quota warnings" value={data.quota_events} sub="Claude subscription limits" />
      </div>

      <Card title="Tasks per day" subtitle="Finished successfully vs. not successful (error, quota, limit, cancelled, incomplete)"
        actions={<Legend items={[{ name: "Successful", color: "var(--good)" }, { name: "Not successful", color: "var(--critical)" }, { name: "Running", color: "var(--accent)" }]} />}>
        <StackedColumns ariaLabel="Agent tasks per day" data={data.per_day.map((d) => ({ label: d.day.slice(5), values: { ok: d.ok, failed: d.failed, running: d.running } }))}
          keys={[{ key: "ok", name: "Successful", color: "var(--good)" }, { key: "failed", name: "Not successful", color: "var(--critical)" }, { key: "running", name: "Running", color: "var(--accent)" }]} />
        <TableView columns={[{ key: "day", label: "Day" }, { key: "ok", label: "Successful" }, { key: "failed", label: "Not successful" }, { key: "running", label: "Running" }]}
          rows={data.per_day.map((d) => ({ ...d }))} />
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Most targeted devices" subtitle="Agent actions per host (localhost = the agent's own computer)">
          <BarList items={data.top_devices} emptyText="No actions in this period." />
        </Card>
        <Card title="Most used tools" subtitle="Agent actions per tool">
          <BarList items={data.top_tools.map((t) => ({ name: t.name, count: t.count, note: `${t.failed} failed` }))} emptyText="No actions in this period." />
          <TableView columns={[{ key: "name", label: "Tool" }, { key: "count", label: "Actions" }, { key: "failed", label: "Failed" }]}
            rows={data.top_tools.map((t) => ({ ...t }))} />
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Inventory status" subtitle={`${inv.total} device(s) now`}>
          <SegmentedBar parts={statusParts} />
        </Card>
        <Card title="Windows versions" subtitle="All devices">
          <BarList items={topWithOther(inv.by_os, 7)} />
          <TableView columns={[{ key: "name", label: "Windows version" }, { key: "count", label: "Devices" }]} rows={inv.by_os.map((r) => ({ ...r }))} />
        </Card>
        <Card title="Devices by department" subtitle="Unknown = no hierarchy data">
          <BarList items={topWithOther(inv.by_department, 7)} />
          <TableView columns={[{ key: "name", label: "Department" }, { key: "count", label: "Devices" }]} rows={inv.by_department.map((r) => ({ ...r }))} />
        </Card>
      </div>
    </div>
  );
}
