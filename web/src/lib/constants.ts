// Qurilma holati ranglari: status palitrasi (good/warning) + neytral kulrang; har doim legenda/yorliq bilan.
export const STATUS_PARTS = [
  { key: "online", name: "Online (this PC)", color: "var(--good)" },
  { key: "active", name: "Active in AD", color: "#199e70" },
  { key: "stale", name: "Inactive in AD", color: "var(--warning)" },
  { key: "disabled", name: "Disabled", color: "#6b6a66" },
  { key: "unknown", name: "Unknown", color: "#45443f" },
];

export function topWithOther(items: { name: string; count: number }[], n: number) {
  if (items.length <= n) return items;
  const rest = items.slice(n).reduce((a, i) => a + i.count, 0);
  return [...items.slice(0, n), { name: "Other", count: rest }];
}

export const UNKNOWN_KEY = "__unknown__";
