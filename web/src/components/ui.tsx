"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { DeviceStatus } from "@/lib/types";
import { UNKNOWN } from "@/lib/format";
import { IconAlert, IconCheck, IconClock, IconDot, IconMinus, IconX } from "./icons";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-1 max-w-3xl text-sm text-ink-3">{subtitle}</p> : null}
      </div>
      {actions ? <div className="no-print flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Card({ title, subtitle, actions, children, className = "", bodyClass = "p-5" }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface ${className}`}>
      {title || actions ? (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div>
            {title ? <h2 className="text-sm font-semibold">{title}</h2> : null}
            {subtitle ? <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p> : null}
          </div>
          {actions ? <div className="no-print flex items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function StatTile({ label, value, sub, href, accent }: {
  label: string; value: ReactNode; sub?: ReactNode; href?: string; accent?: ReactNode;
}) {
  const body = (
    <div className="h-full rounded-xl border border-line bg-surface p-5 transition-colors hover:border-white/20">
      <div className="flex items-center justify-between text-xs font-medium text-ink-3">
        <span>{label}</span>
        {accent}
      </div>
      <div className="mt-2 text-3xl font-semibold tracking-tight">{value}</div>
      {sub ? <div className="mt-1.5 text-xs text-ink-2">{sub}</div> : null}
    </div>
  );
  return href ? <Link href={href} className="block h-full">{body}</Link> : body;
}

export function Unknown({ value, mono }: { value: ReactNode; mono?: boolean }) {
  if (value === null || value === undefined || value === "") return <span className="text-ink-3">{UNKNOWN}</span>;
  return <span className={mono ? "font-mono text-[12px]" : undefined}>{value}</span>;
}

const STATUS: Record<string, { label: string; color: string; icon: typeof IconDot }> = {
  online: { label: "Online", color: "var(--good)", icon: IconDot },
  active: { label: "Active (AD)", color: "var(--good)", icon: IconCheck },
  stale: { label: "Inactive (AD)", color: "var(--warning)", icon: IconClock },
  disabled: { label: "Disabled (AD)", color: "var(--ink-3)", icon: IconMinus },
  unknown: { label: "Unknown", color: "var(--ink-3)", icon: IconMinus },
  ok: { label: "Success", color: "var(--good)", icon: IconCheck },
  error: { label: "Error", color: "var(--critical)", icon: IconX },
  failed: { label: "Failed", color: "var(--critical)", icon: IconX },
  quota: { label: "Quota limit", color: "var(--serious)", icon: IconAlert },
  limit: { label: "Limit reached", color: "var(--serious)", icon: IconAlert },
  refusal: { label: "Refused", color: "var(--serious)", icon: IconAlert },
  cancelled: { label: "Cancelled", color: "var(--ink-3)", icon: IconMinus },
  running: { label: "Running", color: "var(--accent)", icon: IconClock },
  incomplete: { label: "Incomplete", color: "var(--warning)", icon: IconAlert },
};

export function statusMeta(status: string) {
  return STATUS[status] || { label: status || UNKNOWN, color: "var(--ink-3)", icon: IconMinus };
}

export function StatusChip({ status, title }: { status: DeviceStatus | string; title?: string | null }) {
  const m = statusMeta(status);
  const Icon = m.icon;
  return (
    <span title={title || undefined}
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface-2 px-2 py-0.5 text-xs text-ink-2">
      <Icon width={12} height={12} style={{ color: m.color }} />
      {m.label}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-sm text-ink-3">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-3 border-t-accent" />
      {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-critical/40 bg-critical/10 px-4 py-3 text-sm text-ink">
      <IconAlert className="mt-0.5 shrink-0 text-critical" />
      <span>{error}</span>
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${tone === "warn" ? "border-warning/40 bg-warning/10" : "border-accent/30 bg-accent/10"} text-ink-2`}>
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-2 py-10 text-center text-sm text-ink-3">{children}</div>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-ink">{children}</dd>
    </div>
  );
}

export function Button({ children, onClick, disabled, variant = "secondary", type = "button", title }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "secondary" | "ghost";
  type?: "button" | "submit"; title?: string;
}) {
  const styles = {
    primary: "bg-accent text-white hover:bg-accent/90",
    secondary: "border border-line bg-surface-2 text-ink hover:bg-surface-3",
    ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title}
      className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles}`}>
      {children}
    </button>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { value: T; label: string; count?: number }[];
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5" role="tablist">
      {items.map((it) => (
        <button key={it.value} role="tab" aria-selected={value === it.value} onClick={() => onChange(it.value)}
          className={`rounded-md px-3 py-1.5 text-sm transition-colors ${value === it.value ? "bg-surface-3 text-ink" : "text-ink-3 hover:text-ink"}`}>
          {it.label}
          {it.count !== undefined ? <span className="ml-1.5 text-xs text-ink-3">{it.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Select({ value, onChange, options, label }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-3">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="min-w-36 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-ink">
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function SearchInput({ value, onChange, placeholder = "Search…" }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-3">
      Search
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-64 max-w-full rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-3" />
    </label>
  );
}

export function Table({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className={`w-full border-collapse text-left text-sm ${wide ? "min-w-[900px]" : ""}`}>{children}</table>
    </div>
  );
}

export function Th({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return (
    <th className={`sticky top-0 border-b border-line bg-surface px-3 py-2.5 text-xs font-medium text-ink-3 ${className}`}>
      {children}
    </th>
  );
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <td className={`border-b border-line/60 px-3 py-2.5 align-top ${className}`}>{children}</td>;
}

export function Pager({ page, pages, onPage, total }: {
  page: number; pages: number; onPage: (p: number) => void; total: number;
}) {
  if (pages <= 1) return <div className="px-4 py-3 text-xs text-ink-3">{total} item(s)</div>;
  return (
    <div className="no-print flex items-center justify-between gap-3 px-4 py-3 text-xs text-ink-3">
      <span>{total} item(s) · page {page + 1} of {pages}</span>
      <div className="flex gap-2">
        <Button variant="ghost" disabled={page === 0} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button variant="ghost" disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}
