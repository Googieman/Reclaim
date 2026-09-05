"use client";

import { useState } from "react";
import { resolveEscalation, ReclaimApiError, type Escalation } from "@/lib/api";

interface EscalationPanelProps {
  readonly tenantId: string;
  readonly escalation?: Escalation | null;
  readonly readOnly?: boolean;
  readonly onRecorded?: () => void;
}

export function EscalationPanel({ tenantId, escalation, readOnly = false, onRecorded }: EscalationPanelProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const canResolve = !readOnly && Boolean(escalation?.escalation_id && escalation.state === "open");

  async function recordOwnerFollowUp() {
    if (!escalation?.escalation_id) return;
    setBusy(true);
    setMessage(null);
    try {
      await resolveEscalation(tenantId, { escalationId: escalation.escalation_id, expectedVersion: escalation.expected_version });
      setMessage("Owner follow-up request recorded; refreshing authoritative state.");
      onRecorded?.();
    } catch (error) {
      setMessage(error instanceof ReclaimApiError ? error.message : "The escalation follow-up could not be recorded.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="subpanel escalation-panel" aria-labelledby="escalation-title">
      <div className="subpanel-heading"><div><p className="section-kicker">Human ownership</p><h3 id="escalation-title">Escalation</h3></div><span className={`state-label state-label--${escalation ? "uncertain" : "legitimate"}`}>{escalation?.state?.replaceAll("_", " ") ?? "Not required"}</span></div>
      {readOnly ? <p className="blocking-note">REPLAY is read-only. Escalation commands are unavailable.</p> : null}
      {escalation ? (
        <>
          {!escalation.owner_id ? <p className="blocking-note">Owner missing — unresolved work cannot be silently cleared.</p> : null}
          <dl className="field-list field-list--two-column">
            <Field label="Owner" value={escalation.owner_id ?? "No tenant-scoped owner"} mono />
            <Field label="Remaining exposure" value={formatMinor(escalation.remaining_exposure_minor, escalation.currency)} />
            <Field label="Reason" value={escalation.reason} />
            <Field label="Recommended next action" value={escalation.recommended_human_decision} />
            <Field label="Evidence" value={escalation.evidence_references.join(" · ")} mono />
            <Field label="Linked execution" value={escalation.execution_id ?? "Not linked"} mono />
          </dl>
          {canResolve ? <button type="button" className="button button--quiet consequential-command" disabled={busy} onClick={recordOwnerFollowUp}>{busy ? "Recording…" : "Record owner follow-up"}</button> : null}
        </>
      ) : <p className="panel-copy">Inconclusive verification or unresolved exposure will appear here with an owner and recommended decision.</p>}
      {message ? <p className="command-message" role="status">{message}</p> : null}
    </section>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="field-item"><dt>{label}</dt><dd className={mono ? "mono" : undefined}>{value}</dd></div>;
}

function formatMinor(value: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(value / 100);
}
