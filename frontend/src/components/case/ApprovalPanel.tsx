"use client";

import { useState } from "react";
import { approveApproval, rejectApproval, type Approval, type PolicyDecision, type Proposal, ReclaimApiError } from "@/lib/api";

interface ApprovalPanelProps {
  readonly tenantId: string;
  readonly approval?: Approval | null;
  readonly proposal?: Proposal | null;
  readonly policyDecision?: PolicyDecision | null;
  readonly readOnly?: boolean;
  readonly onRecorded?: () => void;
}

export function ApprovalPanel({ tenantId, approval, proposal, policyDecision, readOnly = false, onRecorded }: ApprovalPanelProps) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const canDecide = !readOnly && Boolean(approval?.request_id && ["required", "pending"].includes(approval.status));

  async function recordDecision(kind: "approve" | "reject") {
    if (!approval?.request_id) return;
    setBusy(kind);
    setMessage(null);
    try {
      const command = { requestId: approval.request_id, expectedVersion: approval.expected_version };
      if (kind === "approve") await approveApproval(tenantId, command);
      else await rejectApproval(tenantId, command);
      setMessage(kind === "approve" ? "Approval request recorded; refreshing authoritative state." : "Rejection request recorded; refreshing authoritative state.");
      onRecorded?.();
    } catch (error) {
      setMessage(error instanceof ReclaimApiError ? error.message : "The approval decision could not be recorded.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="subpanel approval-panel" aria-labelledby="approval-title">
      <div className="subpanel-heading"><div><p className="section-kicker">Human gate</p><h3 id="approval-title">Approval</h3></div><span className={`state-label state-label--${approval?.status ?? "uncertain"}`}>{approval?.status?.replaceAll("_", " ") ?? "Not required"}</span></div>
      {readOnly ? <p className="blocking-note">REPLAY is read-only. Approval commands are unavailable.</p> : null}
      {approval && canDecide && proposal ? (
        <>
          <p className="approval-warning">Review the exact action below. Recording approval permits backend eligibility; it does not prove execution or success.</p>
          <dl className="field-list field-list--two-column">
            <Field label="Action" value={proposal.action_type} />
            <Field label="Target" value={proposal.target_resource} mono />
            <Field label="Amount / currency" value={proposal.amount_minor === null || proposal.amount_minor === undefined ? "Not applicable" : formatMinor(proposal.amount_minor, proposal.currency ?? "INR")} />
            <Field label="Policy result" value={policyDecision?.result?.replaceAll("_", " ") ?? "Not supplied"} />
            <Field label="Policy version" value={policyDecision?.policy_version_id ?? "Not supplied"} mono />
            <Field label="Proposer" value={approval.proposer_id ?? proposal.proposer_id ?? "Not supplied"} mono />
            <Field label="Approver role" value={approval.approver_role ?? "Independent approver required"} />
            <Field label="Resource state" value={proposal.current_resource_state ?? "Not supplied"} />
          </dl>
          <div className="approval-actions" aria-label="Approval decisions">
            <button type="button" className="button button--approve consequential-command" disabled={busy !== null} onClick={() => recordDecision("approve")}>{busy === "approve" ? "Recording…" : "Approve exact action"}</button>
            <button type="button" className="button button--reject consequential-command" disabled={busy !== null} onClick={() => recordDecision("reject")}>{busy === "reject" ? "Recording…" : "Reject exact action"}</button>
          </div>
        </>
      ) : (
        <p className="panel-copy">{approval?.reason ?? (approval?.status === "approved" ? "An independent approver has recorded this decision." : "No approval command is available for the current authoritative state." )}</p>
      )}
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
