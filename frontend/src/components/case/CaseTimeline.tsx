"use client";

import { Fragment, useMemo, useState } from "react";
import type { TimelineEvent } from "@/lib/api";

interface CaseTimelineProps {
  readonly events: readonly TimelineEvent[];
  readonly onOpenAudit?: (reference: string) => void;
}

type AttributionFilter = "all" | "malicious" | "legitimate" | "uncertain";

const attributionCopy: Record<Exclude<AttributionFilter, "all">, { label: string; glyph: string }> = {
  malicious: { label: "Malicious", glyph: "!" },
  legitimate: { label: "Legitimate", glyph: "✓" },
  uncertain: { label: "Uncertain", glyph: "?" },
};

export function CaseTimeline({ events, onOpenAudit }: CaseTimelineProps) {
  const [filter, setFilter] = useState<AttributionFilter>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const filteredEvents = useMemo(
    () => (filter === "all" ? events : events.filter((event) => event.attribution === filter)),
    [events, filter],
  );

  return (
    <section className="panel timeline-panel" id="investigation" aria-labelledby="investigation-title">
      <div className="panel-heading panel-heading--with-controls">
        <div>
          <p className="section-kicker">Chronology</p>
          <h2 id="investigation-title">Incident investigation</h2>
          <p className="panel-subtitle">
            Authoritative timeline · {events.length} event{events.length === 1 ? "" : "s"}
          </p>
        </div>
        <label className="filter-control">
          <span>Attribution</span>
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value as AttributionFilter)}
            aria-label="Filter timeline by attribution"
          >
            <option value="all">All activity</option>
            <option value="malicious">Malicious</option>
            <option value="legitimate">Legitimate</option>
            <option value="uncertain">Uncertain</option>
          </select>
        </label>
      </div>

      <p className="filter-scope" aria-live="polite">
        Showing {filteredEvents.length} of {events.length} events · case totals are unchanged
      </p>

      {filteredEvents.length === 0 ? (
        <div className="empty-state">
          <span className="empty-state__mark" aria-hidden="true">—</span>
          <div>
            <strong>No events in this view</strong>
            <p>{events.length === 0 ? "Collection is pending or no timeline facts are available." : "Try a different attribution filter."}</p>
          </div>
        </div>
      ) : (
        <div className="timeline-table-wrap">
          <table className="timeline-table">
            <caption className="sr-only">Chronological incident activity and evidence provenance</caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Event / resource</th>
                <th scope="col">Attribution</th>
                <th scope="col">Confidence / rationale</th>
                <th scope="col">Evidence</th>
                <th scope="col">Financial impact</th>
                <th scope="col">Provenance</th>
                <th scope="col"><span className="sr-only">Details</span></th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((event) => {
                const expanded = expandedId === event.event_id;
                const attribution = event.attribution ?? "uncertain";
                const copy = attributionCopy[attribution];
                const detailId = `event-detail-${event.event_id}`;
                return (
                  <Fragment key={event.event_id}>
                  <tr className={expanded ? "timeline-row timeline-row--expanded" : "timeline-row"}>
                    <td className="mono timeline-time">
                      <span className="chronology-line" aria-hidden="true" />
                      {formatTimestamp(event.effective_at ?? event.occurred_at)}
                    </td>
                    <td>
                      <strong>{event.canonical_event_type}</strong>
                      <span className="table-secondary">{event.resource ?? event.source_identity ?? "Merchant observation"}</span>
                    </td>
                    <td>
                      <span className={`state-label state-label--${attribution}`}>
                        <span aria-hidden="true">{copy.glyph}</span>
                        <span>{copy.label}</span>
                      </span>
                    </td>
                    <td>
                      <span className="confidence-value">{formatConfidence(event.confidence)}</span>
                      <span className="table-secondary">{event.rationale ?? (copy.label === "Uncertain" ? "Evidence does not support a conclusion." : "Advisory attribution")}</span>
                    </td>
                    <td>
                      {event.evidence_references.length > 0 ? (
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => onOpenAudit?.(event.evidence_references[0])}
                        >
                          {event.evidence_references.length} reference{event.evidence_references.length === 1 ? "" : "s"}
                        </button>
                      ) : (
                        <span className="table-secondary">None recorded</span>
                      )}
                    </td>
                    <td className="money-cell">
                      {event.financial_impact_minor === null || event.financial_impact_minor === undefined
                        ? "—"
                        : formatMinor(event.financial_impact_minor, event.currency ?? "INR")}
                    </td>
                    <td>
                      <span className="table-secondary">{event.provenance.method ?? event.source_identity ?? "Recorded evidence"}</span>
                      <span className="mono table-secondary">{event.provenance.version ?? "version pending"}</span>
                    </td>
                    <td className="detail-cell">
                      <button
                        type="button"
                        className="icon-button"
                        aria-expanded={expanded}
                        aria-controls={detailId}
                        aria-label={`${expanded ? "Collapse" : "Expand"} ${event.event_id}`}
                        onClick={() => setExpandedId(expanded ? null : event.event_id)}
                      >
                        {expanded ? "−" : "+"}
                      </button>
                    </td>
                  </tr>
                    {expanded ? (
                  <tr className="timeline-detail-row">
                      <td colSpan={8} className="timeline-detail" id={detailId}>
                        <div className="timeline-detail-grid">
                          <Detail label="Event ID" value={event.event_id} mono />
                          <Detail label="Source timestamp" value={event.occurred_at} mono />
                          <Detail label="Evidence references" value={event.evidence_references.join(", ") || "None recorded"} mono />
                          <Detail label="Uncertainty reason" value={event.uncertainty_reasons.join("; ") || "No uncertainty reason recorded"} />
                          <Detail label="Source event IDs" value={event.source_event_ids.join(", ") || "None recorded"} mono />
                          <Detail label="Checksum" value={event.provenance.checksum ?? "Not supplied"} mono />
                        </div>
                      </td>
                  </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="detail-item">
      <span className="detail-label">{label}</span>
      <span className={mono ? "mono" : undefined}>{value}</span>
    </div>
  );
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-IN", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatConfidence(value: number | null | undefined): string {
  return value === null || value === undefined ? "Not scored" : `${Math.round(value * 100)}% advisory`;
}

function formatMinor(value: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(value / 100);
}
