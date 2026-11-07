"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { BarList } from "@/components/charts";
import { Card, ErrorBox, Loading, PageHeader, SearchInput, Table, Td, Th } from "@/components/ui";
import { UNKNOWN_KEY } from "@/lib/constants";
import { useApi, usePageTitle } from "@/lib/hooks";
import type { OrgNode } from "@/lib/types";

interface Row {
  org: string | null;
  object: string | null;
  department: string | null;
  count: number;
  online: number;
  active: number;
  stale: number;
  other: number;
}

type SortKey = "department" | "object" | "org" | "count" | "active" | "stale";

export default function DepartmentsPage() {
  usePageTitle("Departments");
  const router = useRouter();
  const { data, error, loading } = useApi<{ tree: OrgNode[] }>("/api/hierarchy");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "count", desc: true });

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    for (const o of data?.tree || []) for (const ob of o.objects) for (const d of ob.departments) {
      const s = d.status;
      out.push({ org: o.name, object: ob.name, department: d.name, count: d.count, online: s.online || 0,
        active: s.active || 0, stale: s.stale || 0, other: (s.disabled || 0) + (s.unknown || 0) });
    }
    return out;
  }, [data]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = t ? rows.filter((r) => [r.org, r.object, r.department].some((x) => (x || "unknown").toLowerCase().includes(t))) : rows;
    const val = (r: Row) => sort.key === "org" ? r.org || "~" : sort.key === "object" ? r.object || "~" : sort.key === "department" ? r.department || "~" : r[sort.key];
    return [...list].sort((a, b) => {
      const va = val(a), vb = val(b);
      const c = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sort.desc ? -c : c;
    });
  }, [rows, q, sort]);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;

  const named = rows.filter((r) => r.department);
  const head = (key: SortKey, label: string, right = false) => (
    <Th className={right ? "text-right" : ""}>
      <button onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key === "count" || key === "active" || key === "stale" }))}
        className="hover:text-ink">
        {label}{sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    </Th>
  );
  const open = (r: Row) => {
    const p = new URLSearchParams({ org: r.org ?? UNKNOWN_KEY, object: r.object ?? UNKNOWN_KEY, department: r.department ?? UNKNOWN_KEY });
    router.push(`/devices/?${p.toString()}`);
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Departments" subtitle={`${named.length} department(s) with known hierarchy; click a row to see its devices.`} />

      <Card title="Devices per department" subtitle="Departments with known hierarchy, largest first">
        <BarList items={[...named].sort((a, b) => b.count - a.count).slice(0, 12).map((r) => ({ name: r.department as string, count: r.count, note: `${r.object ?? "Unknown"} · ${r.org ?? "Unknown"}` }))}
          emptyText="No department data yet — see Organizations for how to add it." />
      </Card>

      <Card bodyClass="p-0" title="All departments"
        actions={<SearchInput value={q} onChange={setQ} placeholder="Department, object, organization" />}>
        <Table wide>
          <thead>
            <tr>
              {head("department", "Department")}{head("object", "Object")}{head("org", "Organization")}
              {head("count", "Devices", true)}{head("active", "Active", true)}{head("stale", "Inactive", true)}
              <Th className="text-right">Disabled / unknown</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={`${r.org}/${r.object}/${r.department}`} onClick={() => open(r)}
                className="cursor-pointer hover:bg-surface-2/60" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && open(r)}>
                <Td>{r.department ?? <span className="text-ink-3">Unknown</span>}</Td>
                <Td className="text-ink-2">{r.object ?? <span className="text-ink-3">Unknown</span>}</Td>
                <Td className="text-ink-2">{r.org ?? <span className="text-ink-3">Unknown</span>}</Td>
                <Td className="tabular text-right">{r.count}</Td>
                <Td className="tabular text-right text-ink-2">{r.active + r.online}</Td>
                <Td className="tabular text-right text-ink-2">{r.stale}</Td>
                <Td className="tabular text-right text-ink-3">{r.other}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
