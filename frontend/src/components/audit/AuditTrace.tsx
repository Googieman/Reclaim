"use client";

import { useState } from "react";
import type { AuditRecord } from "@/lib/api";

interface AuditTraceProps {
  readonly records: readonly AuditRecord[];
  readonly anchor?: string | null;
}

export function AuditTrace({ records, anchor }: AuditTraceProps) {
  const [view, setView] = useState<"narrative" | "technical">("narrative");

  return (
    <section className="audit-trace" id="audit" aria-labelledby="audit-title">
      <div className="audit-heading">
        <div><p className="section-kicker">Append-only provenance</p><h2 id="audit-title">Audit trace</h2><span className="audit-readonly">Read-only · {records.length} records</span></div>
        <div className="trace-tabs" role="tablist" aria-label="Audit presentation">
          <button id="audit-tab-narrative" type="button" role="tab" aria-selected={view === "narrative"} aria-controls="audit-view" className={view === "narrative" ? "trace-tab trace-tab--active" : "trace-tab"} onClick={() => setView("narrative")}>Narrative</button>
          <button id="audit-tab-technical" type="button" role="tab" aria-selected={view === "technical"} aria-controls="audit-view" className={view === "technical" ? "trace-tab trace-tab--active" : "trace-tab"} onClick={() => setView("technical")}>Technical chain</button>
        </div>
      </div>
      {anchor ? <p className="trace-anchor" role="status">Focused reference: <span className="mono">{anchor}</span></p> : null}
      <div id="audit-view" role="tabpanel" tabIndex={0} aria-labelledby={`audit-tab-${view}`}>
        {records.length === 0 ? <p className="panel-copy">No audit records are available from the authoritative source.</p> : <div className="audit-list">{records.map((record) => <AuditRecordRow key={record.audit_id} record={record} view={view} />)}</div>}
      </div>
    </section>
  );
}

function AuditRecordRow({ record, view }: { record: AuditRecord; view: "narrative" | "technical" }) {
  return (
    <article className="audit-record">
      <div className="audit-record__marker" aria-hidden="true">{record.outcome === "recorded" ? "·" : "✓"}</div>
      <div className="audit-record__body">
        <div className="audit-record__topline"><strong>{record.narrative ?? `${record.actor} recorded ${record.action}`}</strong><time dateTime={record.recorded_at}>{formatTimestamp(record.recorded_at)}</time></div>
        {view === "narrative" ? <p>{record.outcome.replaceAll("_", " ")} · evidence and authority are linked below.</p> : <dl className="technical-chain"><Tech label="Audit ID" value={record.audit_id} /><Tech label="Actor / action" value={`${record.actor} · ${record.action}`} /><Tech label="Correlation" value={record.correlation_ids.join(" · ") || "Not supplied"} /><Tech label="Evidence" value={record.evidence_references.join(" · ") || "Not supplied"} /><Tech label="Policy / model" value={`${record.policy_version_id ?? "—"} · ${record.model_version ?? "—"}`} /><Tech label="Previous checksum" value={record.previous_record_checksum ?? "Root record"} /><Tech label="Record checksum" value={record.record_checksum} /></dl>}
      </div>
    </article>
  );
}

function Tech({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd className="mono">{value}</dd></div>; }

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-IN", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}
