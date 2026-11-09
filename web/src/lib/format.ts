export const UNKNOWN = "Unknown";

export function orUnknown(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return UNKNOWN;
  return String(v);
}

export function bytes(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return UNKNOWN;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : digits)} ${units[i]}`;
}

export function rate(n: number | null | undefined): string {
  if (n === null || n === undefined) return UNKNOWN;
  return `${bytes(n)}/s`;
}

export function pct(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return UNKNOWN;
  return `${n.toFixed(digits)}%`;
}

export function compact(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1000).toFixed(1)}K`;
  return n.toLocaleString("en-US");
}

/** Hamma vaqt Toshkent vaqtida (Asia/Tashkent, UTC+5): baza UTC saqlaydi, brauzer qaerda bo'lmasin bir xil ko'rsatiladi. */
export const TZ = "Asia/Tashkent";
const dtf = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

function tk(iso: string | number | null | undefined): { y: string; mo: string; d: string; h: string; mi: string } | null {
  if (iso === null || iso === undefined || iso === "") return null;
  const d = new Date(typeof iso === "number" ? iso * 1000 : iso);
  if (Number.isNaN(d.getTime())) return null;
  const p = Object.fromEntries(dtf.formatToParts(d).map((x) => [x.type, x.value]));
  return { y: p.year, mo: p.month, d: p.day, h: p.hour, mi: p.minute };
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN;
  const t = tk(iso);
  return t ? `${t.y}-${t.mo}-${t.d} ${t.h}:${t.mi}` : iso;
}

export function dateOnly(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN;
  const t = tk(iso);
  return t ? `${t.y}-${t.mo}-${t.d}` : iso;
}

export function timeOnly(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = tk(iso);
  return t ? `${t.h}:${t.mi}` : iso;
}

/** Grafik vaqt belgisi (UNIX soniya): kunlik shamlar uchun sana, qolganlari uchun vaqt — Toshkent bo'yicha. */
export function tkAxis(sec: number, withDate: boolean): string {
  const t = tk(sec);
  if (!t) return "";
  return withDate ? `${t.d}.${t.mo}` : `${t.h}:${t.mi}`;
}

export function tkFull(sec: number): string {
  const t = tk(sec);
  return t ? `${t.d}.${t.mo}.${t.y} ${t.h}:${t.mi}` : "";
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function duration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return UNKNOWN;
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

export function cpuLabel(cpu: { name: string | null; cores: number | null; threads: number | null } | null): string {
  if (!cpu || !cpu.name) return UNKNOWN;
  const cores = cpu.cores && cpu.threads ? ` · ${cpu.cores}C/${cpu.threads}T` : "";
  return `${cpu.name}${cores}`;
}

export function toCsv(rows: Record<string, unknown>[], columns: { key: string; label: string }[]): string {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : Array.isArray(v) ? v.join("; ") : String(v);
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map((c) => esc(c.label)).join(","), ...rows.map((r) => columns.map((c) => esc(r[c.key])).join(","))]
    .join("\r\n");
}

export function download(filename: string, content: string, type = "text/csv;charset=utf-8") {
  const blob = new Blob(["﻿" + content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
