"use client";

import { Fragment, useState } from "react";
import { BarList, Legend, LineChart, StackedColumns, TableView } from "@/components/charts";
import { IconChevron } from "@/components/icons";
import { Card, Empty, ErrorBox, Loading, Notice, PageHeader, StatTile, StatusChip, Table, Tabs, Td, Th } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useApi, usePageTitle } from "@/lib/hooks";

interface Summary {
  total_analyses: number; no_trade: number; trade_scenarios: number; valid_entries: number; not_triggered: number;
  cancelled: number; pending: number; active: number; tp_hits: number; sl_hits: number; expired: number; ambiguous: number;
  resolved: number; win_rate: number | null; avg_r: number | null; expectancy_r: number | null; total_r: number;
  max_drawdown_r: number; small_sample: boolean;
}
interface Breakdown { key: string; scenarios: number; resolved: number; tp: number; sl: number; win_rate: number | null; expectancy_r: number | null; small_sample: boolean }
interface Recent {
  analysis_id: string; created_at: string; symbol: string; timeframe: string; session: string; kind: string;
  strategy_id: string | null; strategy_version: number | null; direction: string | null; entry: number | null;
  sl: number | null; tp: number | null; rr: number | null; status: string | null; r_multiple: number | null;
}
interface Overview {
  enabled: boolean; group_configured: boolean; group_title: string | null; timezone: string; daily_target: number;
  slots: string[]; twelvedata: boolean; exists: boolean; summary: Summary | null; limitations?: string[];
  by_strategy: Breakdown[]; by_instrument?: Breakdown[]; by_session?: Breakdown[]; by_timeframe?: Breakdown[];
  equity: { ts: string; cum_r: number; r: number }[]; recent: Recent[]; per_day: { day: string; trade: number; no_trade: number }[];
  jobs: { job_key: string; kind: string; scheduled_at: string; status: string; attempts: number; last_error: string | null }[];
  warnings: { ts: string; symbol: string; timeframe: string; kind: string; detail: string }[];
}
type Row = Record<string, unknown>;
type TabKey = "timeline" | "outcomes" | "performance" | "strategies" | "reviews" | "sources" | "experiments" | "reports";

const STATUS_MAP: Record<string, string> = {
  TP_HIT: "ok", SL_HIT: "failed", PENDING: "running", ACTIVE_SIMULATION: "running", NOT_TRIGGERED: "cancelled",
  CANCELLED: "cancelled", EXPIRED: "incomplete", AMBIGUOUS_DATA: "incomplete",
};

function OutcomeChip({ status }: { status: string | null }) {
  if (!status) return <span className="text-xs text-ink-3">—</span>;
  return <span title={status}><StatusChip status={STATUS_MAP[status] || status} /><span className="ml-1.5 font-mono text-[10px] text-ink-3">{status}</span></span>;
}

function num(v: unknown, d = 2) {
  return typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: d }) : "—";
}

function AnalysisDetail({ id }: { id: string }) {
  const { data, error, loading } = useApi<{ analysis: Row; content_hash: string; outcome: Row | null; events: Row[]; publications: Row[]; review: Row | null }>(`/api/trading/analysis/${encodeURIComponent(id)}`);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const a = data.analysis as Record<string, unknown>;
  return (
    <div className="grid grid-cols-1 gap-4 text-xs lg:grid-cols-3">
      <div className="lg:col-span-2">
        <div className="mb-1 text-ink-3">Asl tahlil (o&apos;zgarmas, sha256 {data.content_hash.slice(0, 12)}…)</div>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-page p-3 font-mono text-[11px] text-ink-2">{JSON.stringify(a, null, 1)}</pre>
      </div>
      <div className="flex flex-col gap-3">
        <div>
          <div className="mb-1 text-ink-3">Natija hodisalari</div>
          {data.events.length ? (
            <ul className="flex flex-col gap-1">{data.events.map((e, i) => (
              <li key={i} className="rounded border border-line bg-surface px-2 py-1"><span className="font-mono">{String(e.to_status)}</span> · {dateTime(String(e.market_ts || e.recorded_at))}<div className="text-ink-3">{String(e.detail || "")}</div></li>
            ))}</ul>
          ) : <div className="text-ink-3">Kuzatuv hali boshlanmagan (NO-TRADE yoki yangi)</div>}
        </div>
        <div>
          <div className="mb-1 text-ink-3">Nashr</div>
          {data.publications.length ? data.publications.map((p, i) => (
            <div key={i}>{String(p.kind)}: {String(p.status)}{p.message_id ? ` · message_id ${p.message_id}` : ""}</div>
          )) : <div className="text-ink-3">Guruhga yuborilmagan</div>}
        </div>
        {data.review ? (
          <div><div className="mb-1 text-ink-3">SL tahlili</div><b>{String(data.review.classification)}</b>
            <ul className="list-disc pl-4 text-ink-2">{(data.review.factors as string[] || []).map((f) => <li key={f}>{f}</li>)}</ul></div>
        ) : null}
      </div>
    </div>
  );
}

function TableTab({ name, render }: { name: string; render: (items: Row[]) => React.ReactNode }) {
  const { data, error, loading } = useApi<{ items: Row[] }>(`/api/trading/${name}`, 60000);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data?.items.length) return <Empty>Hali yozuv yo&apos;q.</Empty>;
  return <>{render(data.items)}</>;
}

export default function TradingPage() {
  usePageTitle("Trading Research");
  const { data, error, loading } = useApi<Overview>("/api/trading/overview", 30000);
  const [tab, setTab] = useState<TabKey>("timeline");
  const [open, setOpen] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;
  const s = data.summary;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Trading Research"
        subtitle="Paper trading only — research scenarios, simulated outcomes and strategy experiments. No brokerage connection, no live orders." />
      <Notice tone={data.enabled ? "info" : "warn"}>
        {data.enabled ? "Research scheduler is enabled. " : "Research scheduler is disabled (TRADING_ENABLED=0). "}
        Telegram group: {data.group_configured ? (data.group_title || "configured") : "not authorized — owner runs /trading_guruh <chat_id>"}.
        {" "}Forex/metals data: {data.twelvedata ? "Twelve Data key set" : "no Twelve Data key — crypto only (Binance public data)"}.
        {" "}Schedule ({data.timezone}): {(data.slots || []).join(", ")}.
      </Notice>

      {s ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
          <StatTile label="Analyses" value={s.total_analyses} sub={`${s.trade_scenarios} scenarios · ${s.no_trade} no-trade`} />
          <StatTile label="Valid hypothetical entries" value={s.valid_entries} sub={`${s.not_triggered} not triggered · ${s.cancelled} cancelled`} />
          <StatTile label="TP / SL" value={<span>{s.tp_hits}<span className="text-ink-3"> / </span>{s.sl_hits}</span>} sub={`${s.expired} expired · ${s.ambiguous} ambiguous · ${s.pending + s.active} open`} />
          <StatTile label="Win rate (resolved)" value={s.win_rate === null ? "—" : `${s.win_rate}%`} sub={`n = ${s.resolved}${s.small_sample ? " · small sample" : ""}`} />
          <StatTile label="Expectancy" value={s.expectancy_r === null ? "—" : `${s.expectancy_r > 0 ? "+" : ""}${s.expectancy_r}R`} sub={`total ${num(s.total_r)}R`} />
          <StatTile label="Max simulated drawdown" value={`${num(s.max_drawdown_r)}R`} sub="on cumulative R" />
        </div>
      ) : <Notice tone="warn">No research database yet — it is created when the trading module first runs.</Notice>}

      <div className="no-print">
        <Tabs value={tab} onChange={(v) => { setTab(v); setOpen(null); }} items={[
          { value: "timeline", label: "Timeline" }, { value: "outcomes", label: "Outcomes" }, { value: "performance", label: "Performance" },
          { value: "strategies", label: "Strategies" }, { value: "reviews", label: "SL reviews" }, { value: "sources", label: "Research" },
          { value: "experiments", label: "Experiments" }, { value: "reports", label: "Reports" }]} />
      </div>

      {tab === "timeline" ? (
        <>
          <Card title="Analyses per day" subtitle="Last 14 days: scenarios vs. no-trade decisions"
            actions={<Legend items={[{ name: "Scenario", color: "var(--series-1)" }, { name: "No-trade", color: "#6b6a66" }]} />}>
            <StackedColumns ariaLabel="Analyses per day" data={data.per_day.map((d) => ({ label: d.day.slice(5), values: { trade: d.trade, no_trade: d.no_trade } }))}
              keys={[{ key: "trade", name: "Scenario", color: "var(--series-1)" }, { key: "no_trade", name: "No-trade", color: "#6b6a66" }]} height={180} />
          </Card>
          <Card title="Daily analysis timeline" subtitle="Most recent first — click a row for the immutable original and its outcome events" bodyClass="p-0">
            {data.recent.length === 0 ? <Empty>No analyses yet.</Empty> : (
              <Table wide>
                <thead><tr><Th className="w-8" /><Th>ID / time</Th><Th>Instrument</Th><Th>Decision</Th><Th>Strategy</Th><Th className="text-right">Entry</Th><Th className="text-right">SL / TP</Th><Th className="text-right">R/R</Th><Th>Outcome</Th></tr></thead>
                <tbody>
                  {data.recent.map((r) => (
                    <Fragment key={r.analysis_id}>
                      <tr className="cursor-pointer hover:bg-surface-2/60" onClick={() => setOpen(open === r.analysis_id ? null : r.analysis_id)}>
                        <Td><IconChevron width={14} height={14} className={`text-ink-3 transition-transform ${open === r.analysis_id ? "rotate-90" : ""}`} /></Td>
                        <Td className="whitespace-nowrap text-xs"><span className="font-mono">{r.analysis_id}</span><div className="text-ink-3">{dateTime(r.created_at)} · {r.session}</div></Td>
                        <Td>{r.symbol} <span className="text-xs text-ink-3">{r.timeframe}</span></Td>
                        <Td className="text-xs">{r.kind === "TRADE" ? <b>{r.direction}</b> : <span className="text-ink-3">NO-TRADE</span>}</Td>
                        <Td className="text-xs">{r.strategy_id ? `${r.strategy_id} v${r.strategy_version}` : "—"}</Td>
                        <Td className="tabular text-right text-xs">{num(r.entry, 6)}</Td>
                        <Td className="tabular text-right text-xs">{r.sl ? `${num(r.sl, 6)} / ${num(r.tp, 6)}` : "—"}</Td>
                        <Td className="tabular text-right text-xs">{r.rr ? `1:${r.rr}` : "—"}</Td>
                        <Td>{r.kind === "TRADE" ? <OutcomeChip status={r.status || "PENDING"} /> : <span className="text-xs text-ink-3">—</span>}</Td>
                      </tr>
                      {open === r.analysis_id ? <tr><td colSpan={9} className="border-b border-line bg-page/60 px-5 py-4"><AnalysisDetail id={r.analysis_id} /></td></tr> : null}
                    </Fragment>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </>
      ) : null}

      {tab === "outcomes" ? (
        <Card title="Paper-trading outcome tracker" subtitle="Tracking starts only after the hypothetical entry condition is met; ambiguous candles are never counted as wins" bodyClass="p-0">
          <TableTab name="outcomes" render={(items) => (
            <Table wide>
              <thead><tr><Th>Analysis</Th><Th>Instrument</Th><Th>Strategy</Th><Th>Status</Th><Th>Entry time</Th><Th>Exit time</Th><Th className="text-right">Exit</Th><Th className="text-right">R (net)</Th><Th className="text-right">Cost R</Th></tr></thead>
              <tbody>{items.map((o) => (
                <tr key={String(o.analysis_id)} className="hover:bg-surface-2/60">
                  <Td className="font-mono text-xs">{String(o.analysis_id)}</Td>
                  <Td className="text-xs">{String(o.symbol)} {String(o.timeframe)} · {String(o.direction)}</Td>
                  <Td className="text-xs">{String(o.strategy_id)} v{String(o.strategy_version)}</Td>
                  <Td><OutcomeChip status={String(o.status)} /></Td>
                  <Td className="text-xs text-ink-2">{o.entry_time ? dateTime(String(o.entry_time)) : "—"}</Td>
                  <Td className="text-xs text-ink-2">{o.exit_time ? dateTime(String(o.exit_time)) : "—"}</Td>
                  <Td className="tabular text-right text-xs">{num(o.exit_price, 6)}</Td>
                  <Td className="tabular text-right text-xs">{typeof o.r_multiple === "number" ? `${o.r_multiple > 0 ? "+" : ""}${num(o.r_multiple)}` : "—"}</Td>
                  <Td className="tabular text-right text-xs text-ink-3">{num(o.cost_r)}</Td>
                </tr>))}</tbody>
            </Table>)} />
        </Card>
      ) : null}

      {tab === "performance" ? (
        <>
          <Card title="Cumulative simulated R" subtitle="Resolved scenarios (TP/SL) ordered by exit time">
            {data.equity.length > 1 ? (
              <LineChart ariaLabel="Cumulative R" labels={data.equity.map((e) => e.ts)} format={(v) => `${v.toFixed(1)}R`}
                series={[{ name: "Cumulative R", color: "var(--series-1)", values: data.equity.map((e) => e.cum_r) }]} />
            ) : <Empty>Not enough resolved scenarios yet.</Empty>}
            <TableView columns={[{ key: "ts", label: "Exit" }, { key: "r", label: "R" }, { key: "cum_r", label: "Cumulative R" }]}
              rows={data.equity.map((e) => ({ ts: e.ts, r: e.r, cum_r: e.cum_r }))} />
          </Card>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {(["by_strategy", "by_instrument", "by_session", "by_timeframe"] as const).map((k) => (
              <Card key={k} title={k.replace("by_", "By ")} subtitle="Resolved scenarios per group (sample size shown)">
                <BarList items={(data[k] || []).map((b) => ({ name: b.key, count: b.resolved, note: `TP ${b.tp} / SL ${b.sl} · win ${b.win_rate ?? "—"}% · exp ${b.expectancy_r ?? "—"}R${b.small_sample ? " · small sample" : ""}` }))}
                  emptyText="No scenarios yet." />
                <TableView columns={[{ key: "key", label: "Group" }, { key: "scenarios", label: "Scenarios" }, { key: "resolved", label: "Resolved" }, { key: "tp", label: "TP" }, { key: "sl", label: "SL" }, { key: "win_rate", label: "Win %" }, { key: "expectancy_r", label: "Exp. R" }]}
                  rows={(data[k] || []).map((b) => ({ ...b, win_rate: b.win_rate ?? "—", expectancy_r: b.expectancy_r ?? "—" }))} />
              </Card>
            ))}
          </div>
          {data.limitations ? <Notice>{data.limitations.join(" ")}</Notice> : null}
        </>
      ) : null}

      {tab === "strategies" ? (
        <Card title="Strategy library" subtitle="Every strategy is a hypothesis. Versions are immutable; activation requires the owner (/trading_faollashtir)." bodyClass="p-0">
          <TableTab name="strategies" render={(items) => (
            <Table wide>
              <thead><tr><Th>Strategy</Th><Th>Status</Th><Th>Regimes</Th><Th>Rules</Th><Th>Historical tests (costs included)</Th></tr></thead>
              <tbody>{items.map((st) => {
                const stats = (Array.isArray(st.stats) ? st.stats : []) as Row[];
                return (
                  <tr key={`${st.strategy_id}-${st.version}`} className="align-top">
                    <Td><b>{String(st.strategy_id)}</b> v{String(st.version)}<div className="text-xs text-ink-3">{String(st.name)}</div></Td>
                    <Td className="text-xs">{String(st.status)}</Td>
                    <Td className="text-xs text-ink-2">{(st.regimes as string[] || []).join(", ")}</Td>
                    <Td className="max-w-md text-xs text-ink-2"><div>{String(st.entry_rules)}</div><div className="mt-1 text-ink-3">{String(st.exit_rules)}</div>
                      <div className="mt-1 font-mono text-[10px] text-ink-3">{JSON.stringify(st.params)}</div></Td>
                    <Td className="text-xs">{stats.length ? stats.slice(-3).map((t, i) => (
                      <div key={i} className="mb-1">{String(t.symbol)} {String(t.timeframe)} · n={String(t.sample_size)} · win {String(t.win_rate ?? "—")}% · exp {String(t.expectancy ?? "—")}R · DD {String(t.max_dd ?? "—")}R
                        <div className="text-ink-3">{String(t.period_start).slice(0, 10)} → {String(t.period_end).slice(0, 10)}</div></div>
                    )) : <span className="text-ink-3">not tested yet</span>}</Td>
                  </tr>);
              })}</tbody>
            </Table>)} />
        </Card>
      ) : null}

      {tab === "reviews" ? (
        <Card title="Stop-loss review history" subtitle="One loss does not make a strategy defective; not every loss is an agent mistake" bodyClass="p-0">
          <TableTab name="reviews" render={(items) => (
            <Table wide>
              <thead><tr><Th>Analysis</Th><Th>Strategy</Th><Th>Classification</Th><Th>Factors</Th></tr></thead>
              <tbody>{items.map((r) => (
                <tr key={String(r.analysis_id)} className="align-top">
                  <Td className="font-mono text-xs">{String(r.analysis_id)}<div className="text-ink-3">{String(r.symbol)} {String(r.timeframe)}</div></Td>
                  <Td className="text-xs">{String(r.strategy_id)} v{String(r.strategy_version)}</Td>
                  <Td className="text-xs"><b>{String(r.classification)}</b></Td>
                  <Td className="text-xs text-ink-2">{(r.factors as string[] || []).join("; ") || "—"}</Td>
                </tr>))}</tbody>
            </Table>)} />
        </Card>
      ) : null}

      {tab === "sources" ? (
        <Card title="Research sources" subtitle="Verified findings, opinions and hypotheses are kept separate" bodyClass="p-0">
          <TableTab name="sources" render={(items) => (
            <Table wide>
              <thead><tr><Th>Type</Th><Th>Source</Th><Th>Published / retrieved</Th><Th>Summary</Th></tr></thead>
              <tbody>{items.map((r) => (
                <tr key={String(r.id)} className="align-top">
                  <Td className="text-xs font-mono">{String(r.evidence_type)}</Td>
                  <Td className="max-w-xs text-xs"><a className="text-accent hover:underline" href={String(r.url)} target="_blank" rel="noreferrer noopener">{String(r.title)}</a><div className="text-ink-3">{String(r.publisher || "")} · {String(r.topic)}</div></Td>
                  <Td className="whitespace-nowrap text-xs text-ink-2">{String(r.published_at || "—")}<div className="text-ink-3">{dateTime(String(r.retrieved_at))}</div></Td>
                  <Td className="max-w-xl text-xs text-ink-2">{String(r.summary)}</Td>
                </tr>))}</tbody>
            </Table>)} />
        </Card>
      ) : null}

      {tab === "experiments" ? (
        <Card title="Strategy experiments" subtitle="In-sample / out-of-sample with costs; failed experiments are kept" bodyClass="p-0">
          <TableTab name="experiments" render={(items) => (
            <Table wide>
              <thead><tr><Th>Experiment</Th><Th>Versions</Th><Th>Hypothesis</Th><Th>Verdict</Th><Th>Out-of-sample</Th></tr></thead>
              <tbody>{items.map((e) => {
                const res = e.results as { base?: { out_of_sample?: Row }; candidate?: { out_of_sample?: Row }; explanation?: string } | undefined;
                return (
                  <tr key={String(e.experiment_id)} className="align-top">
                    <Td className="font-mono text-xs">{String(e.experiment_id)}<div className="text-ink-3">{dateTime(String(e.created_at))}</div></Td>
                    <Td className="text-xs">{String(e.strategy_id)} v{String(e.base_version)} → v{String(e.candidate_version)}</Td>
                    <Td className="max-w-md text-xs text-ink-2">{String(e.hypothesis)}<div className="text-ink-3">{String(e.problem)}</div></Td>
                    <Td className="text-xs"><b>{String(e.verdict)}</b><div className="text-ink-3">{res?.explanation}</div></Td>
                    <Td className="text-xs text-ink-2">base exp {String(res?.base?.out_of_sample?.expectancy_r ?? "—")}R (n={String(res?.base?.out_of_sample?.resolved ?? 0)}) · cand exp {String(res?.candidate?.out_of_sample?.expectancy_r ?? "—")}R (n={String(res?.candidate?.out_of_sample?.resolved ?? 0)})</Td>
                  </tr>);
              })}</tbody>
            </Table>)} />
        </Card>
      ) : null}

      {tab === "reports" ? (
        <TableTab name="reports" render={(items) => (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {items.map((r) => (
              <Card key={String(r.report_id)} title={`${String(r.kind)} report · ${String(r.period_end)}`} subtitle={`created ${dateTime(String(r.created_at))}`}>
                <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-ink-2">{String(r.text)}</pre>
              </Card>
            ))}
          </div>)} />
      ) : null}

      {data.warnings.length || data.jobs.length ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Card title="Scheduler jobs" subtitle="Persistent task state (missed slots are recorded, never back-filled)" bodyClass="p-0">
            <Table><tbody>{data.jobs.slice(0, 12).map((j) => (
              <tr key={j.job_key}><Td className="font-mono text-xs">{j.job_key}</Td><Td className="text-xs">{j.status}{j.attempts > 1 ? ` (${j.attempts})` : ""}</Td><Td className="text-xs text-ink-3">{j.last_error || ""}</Td></tr>
            ))}</tbody></Table>
          </Card>
          <Card title="Data-quality warnings" bodyClass="p-0">
            {data.warnings.length ? <Table><tbody>{data.warnings.slice(0, 12).map((w, i) => (
              <tr key={i}><Td className="whitespace-nowrap text-xs">{dateTime(w.ts)}</Td><Td className="text-xs">{w.symbol} {w.timeframe}</Td><Td className="text-xs text-ink-2">{w.kind}: {w.detail}</Td></tr>
            ))}</tbody></Table> : <Empty>No warnings.</Empty>}
          </Card>
        </div>
      ) : null}
    </div>
  );
}
