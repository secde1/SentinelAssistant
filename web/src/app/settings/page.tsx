"use client";

import { useRouter } from "next/navigation";
import { IconCheck, IconLogout, IconShield, IconX } from "@/components/icons";
import { Button, Card, ErrorBox, Field, Loading, Notice, PageHeader, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";
import type { AgentStatus, Source } from "@/lib/types";

interface SettingsResp {
  app: { name: string; version: string; agent_version: string; started: string; python: string; psutil: string; web_build: string | null };
  dashboard: { bind: string; chat_enabled: boolean; sample_sec: number; history_points: number; session_hours: number; stale_days: number; ad_exports: string[]; login_origin: string };
  agent: { home: string; model: string; strong_model: string; effort: string; web_search: boolean; max_concurrent_tasks: number; control_panel: string | null; stt: boolean; reels: boolean; zabbix_poll_sec: number; daily_check_at: string | null };
  secrets_configured: { name: string; configured: boolean }[];
  inventory_entries: number;
  sources: Source[];
  tuzilma_path: string;
  restrictions: string[];
}

const yesNo = (v: boolean) => (v ? "Enabled" : "Disabled");

export default function SettingsPage() {
  usePageTitle("Settings");
  const router = useRouter();
  const { data, error, loading } = useApi<SettingsResp>("/api/settings");
  const agent = useApi<AgentStatus>("/api/agent", 15000);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;
  const a = agent.data;

  async function logout() {
    try { await api.post("/api/logout"); } finally { router.replace("/login/"); }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Settings" subtitle="Current configuration (read-only). Change values in D:\it-agent\.env and restart the dashboard."
        actions={<Button onClick={logout}><IconLogout width={16} height={16} /> Sign out</Button>} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Application">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Name">{data.app.name}</Field>
            <Field label="Version">V{data.app.version} · agent {data.app.agent_version}</Field>
            <Field label="Server started">{dateTime(data.app.started)}</Field>
            <Field label="Web UI build">{data.app.web_build ? dateTime(data.app.web_build) : "Not built"}</Field>
            <Field label="Python · psutil">{data.app.python} · {data.app.psutil}</Field>
            <Field label="Address"><span className="font-mono text-xs">http://{data.dashboard.bind}/</span></Field>
          </dl>
        </Card>
        <Card title="Dashboard">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="AI chat (read-only)">{yesNo(data.dashboard.chat_enabled)}</Field>
            <Field label="Sampling interval">{data.dashboard.sample_sec} s · {data.dashboard.history_points} points kept</Field>
            <Field label="Session length">{data.dashboard.session_hours} h</Field>
            <Field label="Inactive threshold">No AD logon for {data.dashboard.stale_days} days</Field>
            <Field label="Access token">{data.dashboard.login_origin}</Field>
            <Field label="AD export files"><span className="font-mono text-xs">{data.dashboard.ad_exports.join("; ")}</span></Field>
          </dl>
        </Card>
        <Card title="SENTINAL AI agent" subtitle="The Telegram agent runs separately; the dashboard only reads its state">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Status">{a ? (a.running ? `Running (PID ${a.pid ?? "?"})` : a.stopped_by_owner ? "Stopped by owner" : "Not running") : "…"}</Field>
            <Field label="Last heartbeat">{a?.last_alive ? dateTime(a.last_alive) : "Unknown"}</Field>
            <Field label="Model">{data.agent.model} · effort {data.agent.effort}</Field>
            <Field label="Strong model">{data.agent.strong_model}</Field>
            <Field label="Agent home"><span className="font-mono text-xs">{data.agent.home}</span></Field>
            <Field label="Desktop panel">{data.agent.control_panel || "Disabled"}</Field>
            <Field label="Parallel tasks">{data.agent.max_concurrent_tasks}</Field>
            <Field label="Web search">{yesNo(data.agent.web_search)}</Field>
            <Field label="Voice messages (STT)">{yesNo(data.agent.stt)}</Field>
            <Field label="Zabbix polling">{data.agent.zabbix_poll_sec > 0 ? `every ${data.agent.zabbix_poll_sec} s` : "Disabled"}</Field>
            <Field label="Daily check">{data.agent.daily_check_at || "Disabled"}</Field>
            <Field label="Reels studio">{yesNo(data.agent.reels)}</Field>
          </dl>
        </Card>
        <Card title="Secrets" subtitle="Only whether a value is configured — values are never sent to the browser">
          <ul className="flex flex-col gap-2.5 text-sm">
            {data.secrets_configured.map((s) => (
              <li key={s.name} className="flex items-center gap-2">
                {s.configured ? <IconCheck width={16} height={16} className="text-good" /> : <IconX width={16} height={16} className="text-ink-3" />}
                <span className="font-mono text-xs">{s.name}</span>
                <span className="text-xs text-ink-3">{s.configured ? "configured" : "not set"}</span>
              </li>
            ))}
            <li className="text-xs text-ink-3">Agent inventory entries: {data.inventory_entries} (credentials stay in maxfiy/inventar.json)</li>
          </ul>
        </Card>
      </div>

      <Card title="Data sources" bodyClass="p-0">
        <Table wide>
          <thead><tr><Th>Source</Th><Th>Path</Th><Th>Status</Th><Th className="text-right">Records</Th><Th>Updated</Th></tr></thead>
          <tbody>
            {data.sources.map((s) => (
              <tr key={s.label + s.path}>
                <Td>{s.label}</Td>
                <Td className="font-mono text-xs text-ink-2">{s.path}</Td>
                <Td className="text-xs">{s.error ? <span className="text-critical">{s.error}</span> : s.exists ? "Present" : <span className="text-ink-3">Not present</span>}</Td>
                <Td className="tabular text-right">{s.exists ? s.records : "—"}</Td>
                <Td className="tabular text-xs text-ink-2">{s.updated ? dateTime(s.updated) : "—"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card title={<span className="flex items-center gap-2"><IconShield className="text-accent" /> Security boundaries</span>}>
        <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm text-ink-2">
          {data.restrictions.map((r) => <li key={r}>{r}</li>)}
        </ul>
        <div className="mt-4">
          <Notice>Hierarchy assignments file: <span className="font-mono text-ink">{data.tuzilma_path}</span> (see Organizations for the format).</Notice>
        </div>
      </Card>
    </div>
  );
}
