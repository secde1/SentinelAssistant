"use client";

import { Fragment, useEffect, useState } from "react";
import { IconChevron, IconDownload } from "@/components/icons";
import { Button, Card, Empty, ErrorBox, Loading, PageHeader, SearchInput, Select, StatusChip, Table, Tabs, Td, Th } from "@/components/ui";
import { dateTime, download, toCsv } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";
import type { Action, EventItem, Task } from "@/lib/types";

type View = "tasks" | "actions" | "events";
interface Resp<T> { view: View; range: { start: string; end: string }; total: number; items: T[]; truncated: boolean }

function isoDay(d: Date) {
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function presetRange(days: string) {
  const e = new Date();
  const s = new Date();
  s.setDate(e.getDate() - (Number(days) - 1));
  return { start: isoDay(s), end: isoDay(e) };
}

const PRESETS = [
  { value: "1", label: "Today" }, { value: "7", label: "Last 7 days" }, { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" }, { value: "custom", label: "Custom range" },
];

export default function ActivityPage() {
  usePageTitle("Activity History");
  const [view, setView] = useState<View>("tasks");
  const [preset, setPreset] = useState("7");
  const [custom, setCustom] = useState({ start: "", end: "" });
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const { start, end } = preset === "custom" ? custom : presetRange(preset);
  const choosePreset = (v: string) => {
    if (v === "custom") setCustom(presetRange(preset === "custom" ? "7" : preset));
    setPreset(v);
  };

  const params = new URLSearchParams({ view, start, end, q: debounced, status, limit: "500" });
  const { data, error, loading } = useApi<Resp<Task | Action | EventItem>>(start && end ? `/api/activity?${params}` : null, 30000);

  const exportCsv = () => {
    if (!data) return;
    const cols = view === "tasks"
      ? [{ key: "ts", label: "Timestamp" }, { key: "id", label: "Task" }, { key: "devices", label: "Device" }, { key: "description", label: "Task description" },
        { key: "status", label: "Execution result" }, { key: "error", label: "Error information" }, { key: "actions", label: "Actions" }, { key: "origin", label: "Origin" }]
      : view === "actions"
        ? [{ key: "ts", label: "Timestamp" }, { key: "task", label: "Task" }, { key: "host", label: "Device" }, { key: "tool", label: "Tool" },
          { key: "success", label: "Success" }, { key: "detail", label: "Detail" }, { key: "result", label: "Result" }]
        : [{ key: "ts", label: "Timestamp" }, { key: "type", label: "Event" }, { key: "summary", label: "Summary" }];
    download(`sentinal-activity-${view}-${start}_${end}.csv`, toCsv(data.items as never, cols));
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Activity History"
        subtitle="SENTINAL AI task log from the agent journal (already redacted). Business chats and screen activity are not recorded or shown."
        actions={<Button onClick={exportCsv} disabled={!data?.items.length}><IconDownload width={16} height={16} /> Export CSV</Button>} />

      <div className="no-print flex flex-wrap items-end gap-3">
        <Tabs value={view} onChange={(v) => { setView(v); setExpanded(null); }}
          items={[{ value: "tasks", label: "Tasks" }, { value: "actions", label: "Actions" }, { value: "events", label: "System events" }]} />
        <Select label="Period" value={preset} onChange={choosePreset} options={PRESETS} />
        {preset === "custom" ? (
          <>
            <label className="flex flex-col gap-1 text-xs text-ink-3">From
              <input type="date" value={start} onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))} className="rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-ink" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-3">To
              <input type="date" value={end} onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))} className="rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-ink" />
            </label>
          </>
        ) : null}
        <Select label="Result" value={status} onChange={setStatus}
          options={[{ value: "", label: "All" }, { value: "ok", label: "Successful" }, { value: "failed", label: "Failed / errors" }]} />
        <SearchInput value={q} onChange={setQ} placeholder="Text, device, task ID…" />
      </div>

      <Card bodyClass="p-0">
        {error && !data ? <div className="p-4"><ErrorBox error={error} /></div> : loading && !data ? <div className="px-5"><Loading /></div> : !data || data.items.length === 0 ? (
          <Empty>No records for this period and filter.</Empty>
        ) : (
          <>
            <div className="border-b border-line px-5 py-2.5 text-xs text-ink-3">
              {data.total} record(s) · {data.range.start} — {data.range.end}{data.truncated ? ` · showing first ${data.items.length}` : ""}
            </div>
            {view === "tasks" ? (
              <Table wide>
                <thead><tr><Th className="w-8" /><Th>Timestamp</Th><Th>Device</Th><Th>Task description</Th><Th>Execution result</Th><Th>Error information</Th></tr></thead>
                <tbody>
                  {(data.items as Task[]).map((t) => {
                    const open = expanded === t.id;
                    return (
                      <Fragment key={t.id}>
                        <tr className="cursor-pointer hover:bg-surface-2/60" onClick={() => setExpanded(open ? null : t.id)}>
                          <Td><IconChevron width={14} height={14} className={`text-ink-3 transition-transform ${open ? "rotate-90" : ""}`} /></Td>
                          <Td className="tabular whitespace-nowrap text-xs text-ink-2">{dateTime(t.ts)}<div className="font-mono text-[11px] text-ink-3">{t.id}</div></Td>
                          <Td className="max-w-48 text-xs text-ink-2">{t.devices.length ? t.devices.join(", ") : <span className="text-ink-3">—</span>}</Td>
                          <Td className="max-w-xl"><div className="line-clamp-2">{t.description || <span className="text-ink-3">No description</span>}</div>
                            <div className="mt-0.5 text-xs text-ink-3">{t.origin} · {t.actions} action(s){t.mutated ? (t.verified ? " · change verified" : " · change not verified") : ""}</div></Td>
                          <Td><StatusChip status={t.status} /></Td>
                          <Td className="max-w-md text-xs text-ink-2"><div className="line-clamp-2">{t.error || (t.failed_actions ? `${t.failed_actions} failed action(s)` : <span className="text-ink-3">—</span>)}</div></Td>
                        </tr>
                        {open ? (
                          <tr>
                            <td colSpan={6} className="border-b border-line bg-page/60 px-6 py-4">
                              <div className="grid grid-cols-1 gap-4 text-sm lg:grid-cols-2">
                                <div>
                                  <div className="mb-1 text-xs text-ink-3">Request</div>
                                  <div className="whitespace-pre-wrap text-ink-2">{t.description || "—"}</div>
                                  <div className="mb-1 mt-4 text-xs text-ink-3">Agent reply</div>
                                  <div className="max-h-64 overflow-auto whitespace-pre-wrap text-ink-2">{t.result || "—"}</div>
                                </div>
                                <div>
                                  <div className="mb-1 text-xs text-ink-3">Details</div>
                                  <div className="text-xs text-ink-2">Model: {t.model || "Unknown"} · steps: {t.steps} · finished: {t.finished ? dateTime(t.finished) : "—"}</div>
                                  {t.error ? <><div className="mb-1 mt-4 text-xs text-ink-3">Error</div><div className="whitespace-pre-wrap text-xs text-critical">{t.error}</div></> : null}
                                  {t.failures.length ? (
                                    <>
                                      <div className="mb-1 mt-4 text-xs text-ink-3">Failed actions</div>
                                      <ul className="flex flex-col gap-2">
                                        {t.failures.map((f, i) => (
                                          <li key={i} className="rounded-lg border border-line bg-surface p-2 text-xs">
                                            <div className="text-ink-3">{f.ts.slice(11, 19)} · {f.tool} · {f.host}</div>
                                            <div className="mt-1 whitespace-pre-wrap text-ink-2">{f.result}</div>
                                          </li>
                                        ))}
                                      </ul>
                                    </>
                                  ) : null}
                                </div>
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </Table>
            ) : view === "actions" ? (
              <Table wide>
                <thead><tr><Th>Timestamp</Th><Th>Device</Th><Th>Tool</Th><Th>Detail</Th><Th>Execution result</Th></tr></thead>
                <tbody>
                  {(data.items as Action[]).map((a, i) => (
                    <tr key={`${a.ts}-${i}`} className="hover:bg-surface-2/60">
                      <Td className="tabular whitespace-nowrap text-xs text-ink-2">{dateTime(a.ts)}<div className="font-mono text-[11px] text-ink-3">{a.task}</div></Td>
                      <Td className="text-xs text-ink-2">{a.host || "—"}</Td>
                      <Td className="text-xs"><span className="font-mono">{a.tool}</span><div className="text-ink-3">{a.level}{a.duration_ms ? ` · ${a.duration_ms} ms` : ""}</div></Td>
                      <Td className="max-w-md"><div className="line-clamp-3 font-mono text-[11px] text-ink-2" title={a.detail}>{a.detail || "—"}</div></Td>
                      <Td className="max-w-lg"><StatusChip status={a.success ? "ok" : "failed"} /><div className="mt-1 line-clamp-3 text-xs text-ink-2" title={a.result}>{a.result}</div></Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <Table wide>
                <thead><tr><Th>Timestamp</Th><Th>Event</Th><Th>Summary</Th></tr></thead>
                <tbody>
                  {(data.items as EventItem[]).map((e, i) => (
                    <tr key={`${e.ts}-${i}`} className="hover:bg-surface-2/60">
                      <Td className="tabular whitespace-nowrap text-xs text-ink-2">{dateTime(e.ts)}</Td>
                      <Td className="text-xs"><span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full" style={{ background: e.error ? "var(--critical)" : "var(--ink-3)" }} /><span className="font-mono">{e.type}</span></span></Td>
                      <Td className="max-w-3xl text-xs text-ink-2">{e.summary || Object.entries(e.fields).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
