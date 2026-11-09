// Grafik qatlami: zonalar va narx belgilarini lightweight-charts canvas'ida (pane ichida) chizadi.
// Nega canvas: chizma pane bilan bir xil koordinatada, kesilishi (clipping) avtomatik; HTML qatlam kabi sarlavha ustiga chiqmaydi.
// Yorliqlar to'qnashmaydi: vertikal joylashtirish algoritmi (siljitish), sig'maganlari yashiriladi ("+N") va tooltip'da ko'rinadi.
import type { ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";

export type ZoneClass = "support" | "resistance" | "demand" | "supply" | "liquidity" | "range";
export const ZONE_CLASSES: { id: ZoneClass; label: string; short: string }[] = [
  { id: "support", label: "Support", short: "SPT" },
  { id: "resistance", label: "Resistance", short: "RES" },
  { id: "demand", label: "Demand", short: "DMD" },
  { id: "supply", label: "Supply", short: "SPL" },
  { id: "liquidity", label: "Liquidity", short: "LIQ" },
  { id: "range", label: "Diapazon", short: "RNG" },
];

export interface RawZone {
  high: number; low: number; label: string; kind?: string; tf?: string; detector?: string; strength?: number | null; status: string; signal_id: string | null;
}
export interface RawLevel { kind: string; price: number; label: string; side: string; status: string; signal_id: string | null }

export interface Zone {
  id: string; cls: ZoneClass; low: number; high: number; tfs: string[]; detectors: string[]; n: number; active: boolean; strength: number; kinds: string[];
}
export interface Level { id: string; kind: "entry" | "sl" | "tp" | "position"; price: number; text: string; side: string }
export interface LayerOptions { zones: Zone[]; levels: Level[]; hidden: Set<ZoneClass>; showLevels: boolean; showPositions: boolean; lastPrice: number | null }
export interface Hit { title: string; lines: string[]; x: number; y: number }

export function classOf(kind: string | undefined): ZoneClass {
  const k = (kind || "").toLowerCase();
  if (k === "support") return "support";
  if (k === "resistance") return "resistance";
  if (k === "demand") return "demand";
  if (k === "supply") return "supply";
  if (k.startsWith("liq")) return "liquidity";
  return "range";
}

/** Bir xil/ustma-ust zonalarni birlashtiradi (dublikatsiz): bir tur ichida kesishma >= 40% (kichigining kengligidan). */
export function mergeZones(raw: RawZone[]): Zone[] {
  const sorted = raw
    .filter((z) => Number.isFinite(z.low) && Number.isFinite(z.high) && z.high > z.low)
    .map((z) => ({ cls: classOf(z.kind), z }))
    .sort((a, b) => (a.cls === b.cls ? a.z.low - b.z.low : a.cls.localeCompare(b.cls)));
  const out: Zone[] = [];
  for (const { cls, z } of sorted) {
    const last = out[out.length - 1];
    if (last && last.cls === cls) {
      const overlap = Math.min(last.high, z.high) - Math.max(last.low, z.low);
      const minW = Math.min(last.high - last.low, z.high - z.low);
      if (overlap > 0 && overlap / minW >= 0.4) {
        last.low = Math.min(last.low, z.low);
        last.high = Math.max(last.high, z.high);
        last.n += 1;
        last.active = last.active || z.status === "ACTIVE";
        last.strength = Math.max(last.strength, z.strength ?? 0);
        if (z.tf && !last.tfs.includes(z.tf)) last.tfs.push(z.tf);
        if (z.detector && !last.detectors.includes(z.detector)) last.detectors.push(z.detector);
        if (z.kind && !last.kinds.includes(z.kind)) last.kinds.push(z.kind);
        continue;
      }
    }
    out.push({ id: "", cls, low: z.low, high: z.high, tfs: z.tf ? [z.tf] : [], detectors: z.detector ? [z.detector] : [], n: 1, active: z.status === "ACTIVE",
      strength: z.strength ?? 0, kinds: z.kind ? [z.kind] : [] });
  }
  return out.map((z, i) => ({ ...z, id: `${z.cls}-${i}` }));
}

const fmt = (n: number) => Number(n.toPrecision(7)).toString();

function css(name: string, fb: string): string {
  try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fb; } catch { return fb; }
}

interface Pal { good: string; bad: string; accent: string; accent2: string; warn: string; serious: string; liq: string; ink: string; ink3: string; surface: string }
function palette(): Pal {
  return { good: css("--good", "#19c37d"), bad: css("--critical", "#f0524f"), accent: css("--accent", "#2f81f7"), accent2: css("--accent-2", "#22d3ee"),
    warn: css("--warning", "#f5b324"), serious: css("--serious", "#ec835a"), liq: "#a78bfa", ink: css("--ink", "#e8edf4"), ink3: css("--ink-3", "#6f7c8e"), surface: css("--surface", "#0e1218") };
}

function zoneStyle(p: Pal, cls: ZoneClass): { color: string; dash: number[] } {
  switch (cls) {
    case "support": return { color: p.good, dash: [] };
    case "resistance": return { color: p.bad, dash: [] };
    case "demand": return { color: p.accent2, dash: [6, 3] };
    case "supply": return { color: p.serious, dash: [6, 3] };
    case "liquidity": return { color: p.liq, dash: [2, 3] };
    default: return { color: p.warn, dash: [8, 3, 2, 3] };
  }
}

interface Box { x: number; y: number; w: number; h: number }
interface Cand { id: string; pref: number; w: number; text: string; color: string; fg: string; lineY: number }

/** Vertikal joylashtirish: tartiblab, ustma-ust tushganini pastga suradi; sig'maganini yashiradi. */
function place(cands: Cand[], H: number, h: number): { placed: (Cand & { y: number })[]; hidden: number } {
  const sorted = [...cands].sort((a, b) => a.pref - b.pref);
  const placed: (Cand & { y: number })[] = [];
  let bottom = 2 - 2;
  let hidden = 0;
  for (const c of sorted) {
    const y = Math.max(c.pref, bottom + 2, 2);
    if (y + h > H - 2) { hidden += 1; continue; }
    placed.push({ ...c, y });
    bottom = y + h;
  }
  return { placed, hidden };
}

/** Zona yorliqlari: avval 1-ustun, ustma-ust tushsa — o'ng tomondagi keyingi ustun (yorliq o'z zonasidan uzoqlashmaydi).
 *  3 ustunga ham sig'masa yashiriladi (tooltip'da ma'lumot bor). */
function placeColumns(cands: Cand[], H: number, h: number, W: number): { placed: (Cand & { y: number; x: number })[]; hidden: number } {
  const sorted = [...cands].sort((a, b) => a.pref - b.pref);
  const cols: { x: number; bottom: number }[] = [];
  const placed: (Cand & { y: number; x: number })[] = [];
  let hidden = 0;
  let x = 4;
  const widest = Math.max(0, ...sorted.map((c) => c.w));
  for (let i = 0; i < 3; i++) { cols.push({ x, bottom: -1e9 }); x += widest + 6; }
  for (const c of sorted) {
    const y = Math.min(Math.max(c.pref, 2), H - h - 30);  // pastki-chapda TradingView logotipi turadi
    const col = cols.find((k) => y >= k.bottom + 2 && k.x + c.w < W - 90);
    if (!col) { hidden += 1; continue; }
    placed.push({ ...c, y, x: col.x });
    col.bottom = y + h;
  }
  return { placed, hidden };
}

export class ChartLayer implements ISeriesPrimitive<Time> {
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private opts: LayerOptions = { zones: [], levels: [], hidden: new Set(), showLevels: true, showPositions: true, lastPrice: null };
  private zoneBoxes: { zone: Zone; y1: number; y2: number }[] = [];
  private levelBoxes: { level: Level; y: number; pill: Box }[] = [];
  private hover: string | null = null;
  private size = { w: 0, h: 0 };

  attached(p: SeriesAttachedParameter<Time>): void { this.series = p.series; this.requestUpdate = p.requestUpdate; }
  detached(): void { this.series = null; this.requestUpdate = null; }
  setOptions(o: LayerOptions): void { this.opts = o; this.requestUpdate?.(); }
  setHover(id: string | null): void { if (id !== this.hover) { this.hover = id; this.requestUpdate?.(); } }

  /** Kursor ostidagi zona/daraja (tooltip uchun). x,y — pane koordinatasi (CSS px). */
  probe(x: number, y: number): Hit | null {
    for (const b of this.levelBoxes) {
      const p = b.pill;
      if ((x >= p.x && x <= p.x + p.w && y >= p.y && y <= p.y + p.h) || Math.abs(y - b.y) <= 4) {
        const l = b.level;
        return { title: l.text, lines: [`Narx: ${fmt(l.price)}`, l.kind === "position" ? "Ochiq pozitsiya (MT5 DEMO)" : `Signal darajasi (${l.kind.toUpperCase()})`], x, y };
      }
    }
    const hits = this.zoneBoxes.filter((b) => y >= Math.min(b.y1, b.y2) && y <= Math.max(b.y1, b.y2));
    if (!hits.length) return null;
    hits.sort((a, b) => Math.abs(a.y1 - a.y2) - Math.abs(b.y1 - b.y2));
    const z = hits[0].zone;
    const meta = ZONE_CLASSES.find((c) => c.id === z.cls);
    const lines = [`Diapazon: ${fmt(z.low)} – ${fmt(z.high)}`, `Taymfreym: ${z.tfs.join(", ") || "—"} · xodim: ${z.detectors.join(", ") || "—"}`,
      `Kuch: ${z.strength || "—"}${z.n > 1 ? ` · birlashtirilgan: ${z.n} ta` : ""}`, z.active ? "Holat: AKTIV" : "Holat: kutilmoqda"];
    if (hits.length > 1) lines.push(`Shu narxda yana ${hits.length - 1} ta zona`);
    return { title: `${meta?.label ?? z.cls} zonasi`, lines, x, y };
  }

  hoverId(x: number, y: number): string | null {
    const hit = this.zoneBoxes.filter((b) => y >= Math.min(b.y1, b.y2) && y <= Math.max(b.y1, b.y2)).sort((a, b) => Math.abs(a.y1 - a.y2) - Math.abs(b.y1 - b.y2))[0];
    void x;
    return hit ? hit.zone.id : null;
  }

  get hiddenLabels(): number { return this._hiddenLabels; }
  private _hiddenLabels = 0;

  paneViews() {
    return [{
      zOrder: () => "top" as const,
      renderer: () => ({
        draw: (target: { useMediaCoordinateSpace: <T>(f: (s: { context: CanvasRenderingContext2D; mediaSize: { width: number; height: number } }) => T) => T }) => {
          target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => this.paint(ctx, mediaSize.width, mediaSize.height));
        },
      }),
    }];
  }

  private paint(ctx: CanvasRenderingContext2D, W: number, H: number): void {
    const s = this.series;
    this.zoneBoxes = [];
    this.levelBoxes = [];
    if (!s || W < 40 || H < 40) return;
    this.size = { w: W, h: H };
    const p = palette();
    const o = this.opts;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, W, H);
    ctx.clip(); // hech narsa pane'dan tashqariga chiqmaydi
    ctx.font = "600 10px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.textBaseline = "middle";

    // --- zonalar
    const zs = o.zones.filter((z) => !o.hidden.has(z.cls));
    const compact = zs.length > 6;
    const zoneCands: Cand[] = [];
    for (const z of zs) {
      const a = s.priceToCoordinate(z.high);
      const b = s.priceToCoordinate(z.low);
      if (a === null || b === null) continue;
      const top = Math.max(0, Math.min(a, b)), bot = Math.min(H, Math.max(a, b));
      if (bot <= 0 || top >= H || bot - top < 0.5) continue;
      const st = zoneStyle(p, z.cls);
      const hov = this.hover === z.id;
      ctx.globalAlpha = hov ? 0.3 : z.active ? 0.17 : 0.09;
      ctx.fillStyle = st.color;
      ctx.fillRect(0, top, W, Math.max(1.5, bot - top));
      ctx.globalAlpha = hov ? 1 : z.active ? 0.85 : 0.5;
      ctx.strokeStyle = st.color;
      ctx.lineWidth = hov || z.active ? 1.2 : 1;
      ctx.setLineDash(st.dash);
      ctx.beginPath();
      ctx.moveTo(0, top + 0.5); ctx.lineTo(W, top + 0.5);
      ctx.moveTo(0, bot - 0.5); ctx.lineTo(W, bot - 0.5);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      this.zoneBoxes.push({ zone: z, y1: top, y2: bot });
      const meta = ZONE_CLASSES.find((c) => c.id === z.cls)!;
      const text = compact ? `${meta.short} ${z.tfs[0] ?? ""}${z.n > 1 ? ` ×${z.n}` : ""}` : `${meta.label} ${z.tfs.join("·")}${z.n > 1 ? ` ×${z.n}` : ""}${z.active ? " ●" : ""}`;
      const w = ctx.measureText(text).width + 10;
      zoneCands.push({ id: z.id, pref: bot - top >= 16 ? top + 3 : (top + bot) / 2 - 7, w, text, color: st.color, fg: p.ink, lineY: top });
    }

    // --- narx darajalari (Entry/SL/TP/Position): haqiqiy narxda chiziq, yorliq esa to'qnashmaslik uchun siljiydi
    const levels = o.levels.filter((l) => (l.kind === "position" ? o.showPositions : o.showLevels));
    const levelCands: Cand[] = [];
    for (const l of levels) {
      const y = s.priceToCoordinate(l.price);
      if (y === null || y < 0 || y > H) continue;
      const color = l.kind === "tp" ? p.good : l.kind === "sl" ? p.bad : l.kind === "position" ? p.accent2 : p.accent;
      ctx.strokeStyle = color;
      ctx.lineWidth = l.kind === "position" ? 1.8 : 1.2;
      ctx.setLineDash(l.kind === "entry" || l.kind === "position" ? [] : [5, 3]);
      ctx.globalAlpha = 0.95;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      const text = `${l.text}  ${fmt(l.price)}`;
      levelCands.push({ id: l.id, pref: y - 8, w: ctx.measureText(text).width + 12, text, color, fg: "#fff", lineY: y });
      this.levelBoxes.push({ level: l, y, pill: { x: 0, y: 0, w: 0, h: 0 } });
    }

    const h = 16;
    const zp = placeColumns(zoneCands, H, h, W);
    for (const c of zp.placed) {
      ctx.fillStyle = p.surface;
      ctx.globalAlpha = 0.85;
      ctx.fillRect(c.x, c.y, c.w, h);
      ctx.globalAlpha = 1;
      ctx.fillStyle = c.color;
      ctx.fillRect(c.x, c.y, 3, h);
      ctx.fillStyle = c.fg;
      ctx.fillText(c.text, c.x + 8, c.y + h / 2 + 0.5);
    }
    const lp = place(levelCands, H, h);
    for (const c of lp.placed) {
      const x = W - c.w - 4;
      if (Math.abs(c.y + h / 2 - c.lineY) > 2) {  // yorliq siljigan — haqiqiy darajaga ulovchi chiziq
        ctx.strokeStyle = c.color; ctx.lineWidth = 1; ctx.globalAlpha = 0.7;
        ctx.beginPath(); ctx.moveTo(x, c.y + h / 2); ctx.lineTo(x - 8, c.lineY); ctx.stroke(); ctx.globalAlpha = 1;
      }
      ctx.fillStyle = c.color;
      ctx.beginPath();
      ctx.roundRect(x, c.y, c.w, h, 3);
      ctx.fill();
      ctx.fillStyle = c.fg;
      ctx.fillText(c.text, x + 6, c.y + h / 2 + 0.5);
      const box = this.levelBoxes.find((b) => b.level.id === c.id);
      if (box) box.pill = { x, y: c.y, w: c.w, h };
    }
    const hiddenZ = zp.hidden;
    this._hiddenLabels = hiddenZ;
    if (hiddenZ > 0) {  // sig'magan yorliqlar soni — ma'lumot yo'qolmaydi (tooltip'da to'liq)
      const t = `+${hiddenZ} yashirin yorliq`;
      const w = ctx.measureText(t).width + 10;
      const bx = W - w - 8;  // yuqori-o'ng burchak: TradingView logotipi (pastki-chap) bilan to'qnashmaydi
      ctx.fillStyle = p.surface; ctx.globalAlpha = 0.85; ctx.fillRect(bx, 6, w, 16); ctx.globalAlpha = 1;
      ctx.fillStyle = p.ink3; ctx.fillText(t, bx + 5, 14.5);
    }
    ctx.restore();
  }
}
