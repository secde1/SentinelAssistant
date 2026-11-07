"use client";

import Link from "next/link";
import { useState } from "react";
import { SegmentedBar } from "@/components/charts";
import { IconBuilding, IconChevron } from "@/components/icons";
import { Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";
import { STATUS_PARTS, UNKNOWN_KEY } from "@/lib/constants";
import { useApi, usePageTitle } from "@/lib/hooks";
import type { OrgNode, Source } from "@/lib/types";

function devicesHref(org: string | null, object?: string | null, department?: string | null) {
  const p = new URLSearchParams();
  p.set("org", org ?? UNKNOWN_KEY);
  if (object !== undefined) p.set("object", object ?? UNKNOWN_KEY);
  if (department !== undefined) p.set("department", department ?? UNKNOWN_KEY);
  return `/devices/?${p.toString()}`;
}

const EXAMPLE = `{
  "devices": {
    "XS-NB-AUP06": {
      "organization": "Xon Saroy",
      "object": "Head office",
      "department": "АУП"
    }
  }
}`;

export default function OrganizationsPage() {
  usePageTitle("Organizations");
  const { data, error, loading } = useApi<{ tree: OrgNode[]; total: number; tuzilma_path: string; sources: Source[] }>("/api/hierarchy");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;

  const toggle = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Organizations"
        subtitle="Organization → object → department → device, built from existing data only." />

      <Notice>
        Hierarchy comes from AD distinguished names (domain → organization, first OU → object, second OU → department)
        and from manual assignments in <span className="font-mono text-ink">{data.tuzilma_path}</span>. Devices without
        such data are listed under <b>Unknown</b> — nothing is guessed.
      </Notice>

      {data.tree.map((org) => {
        const orgKey = `o:${org.name}`;
        return (
          <Card key={orgKey}
            title={<span className="flex items-center gap-2"><IconBuilding className="text-accent" />{org.name ?? "Unknown organization"}</span>}
            subtitle={`${org.count} device(s) · ${org.objects.length} object(s)`}
            actions={<Link href={devicesHref(org.name)} className="text-xs text-accent hover:underline">View devices</Link>}
            bodyClass="p-0">
            <ul className="divide-y divide-line/60">
              {org.objects.map((ob) => {
                const obKey = `${orgKey}/${ob.name}`;
                const expanded = open[obKey] ?? org.objects.length <= 3;
                return (
                  <li key={obKey}>
                    <button onClick={() => toggle(obKey)} aria-expanded={expanded}
                      className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-surface-2/60">
                      <IconChevron className={`text-ink-3 transition-transform ${expanded ? "rotate-90" : ""}`} />
                      <span className="text-sm font-medium">{ob.name ?? <span className="text-ink-3">Unknown object</span>}</span>
                      <span className="text-xs text-ink-3">{ob.count} device(s) · {ob.departments.length} department(s)</span>
                    </button>
                    {expanded ? (
                      <div className="grid grid-cols-1 gap-3 px-5 pb-4 pl-12 md:grid-cols-2 xl:grid-cols-3">
                        {ob.departments.map((dep) => (
                          <Link key={`${obKey}/${dep.name}`} href={devicesHref(org.name, ob.name, dep.name)}
                            className="rounded-lg border border-line bg-surface-2/50 p-4 transition-colors hover:border-white/20">
                            <div className="flex items-baseline justify-between gap-2">
                              <span className="truncate text-sm font-medium">{dep.name ?? <span className="text-ink-3">Unknown department</span>}</span>
                              <span className="tabular text-sm text-ink-2">{dep.count}</span>
                            </div>
                            <div className="mt-3">
                              <SegmentedBar height={6}
                                parts={STATUS_PARTS.filter((p) => dep.status[p.key]).map((p) => ({ name: p.name, value: dep.status[p.key] || 0, color: p.color }))} />
                            </div>
                          </Link>
                        ))}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </Card>
        );
      })}

      <Card title="Assign devices manually" subtitle="Optional: create this file to set or override the hierarchy per device">
        <p className="mb-3 text-sm text-ink-2">
          Path: <span className="font-mono text-ink">{data.tuzilma_path}</span>. Keys are computer names; any of the
          three fields may be omitted. The dashboard re-reads it on every request. A better long-term source is an AD
          export that includes the <span className="font-mono">DistinguishedName</span> column for all computers.
        </p>
        <pre className="overflow-x-auto rounded-lg border border-line bg-page p-4 font-mono text-xs text-ink-2">{EXAMPLE}</pre>
      </Card>
    </div>
  );
}
