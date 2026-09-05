"use client";

import { useState } from "react";
import { executeApprovedAction, ReclaimApiError } from "@/lib/api";
import type {
  ActionLifecycle,
  Approval,
  ModeAvailability,
  PolicyDecision,
  Proposal,
  Verification,
} from "@/lib/api";

interface ActionDecisionPanelProps {
  readonly proposal?: Proposal | null;
  readonly policyDecision?: PolicyDecision | null;
  readonly approval?: Approval | null;
  readonly action?: ActionLifecycle | null;
  readonly verification?: Verification | null;
  readonly mode: ModeAvailability;
  readonly tenantId: string;
  readonly caseId: string;
  readonly onRecorded?: () => void;
  readonly nextHumanDecision?: string;
}

const lifecycle = ["Proposed", "Policy evaluated", "Approval", "Execution", "Reconciliation", "Verification"];

export function ActionDecisionPanel({
  proposal,
  policyDecision,
  approval,
  action,
  verification,
  mode,
  tenantId,
  caseId,
  onRecorded,
  nextHumanDecision,
}: ActionDecisionPanelProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const isReplay = mode.final_mode !== "live";
  const isEscalation = mode.final_mode === "escalation";
  const isUnknown = action?.status === "unknown";
  const isInconclusive = verification?.status === "inconclusive";

  return (
    <section className="panel decision-panel" id="decision" aria-labelledby="decision-title">
      <div className="panel-heading">
        <p className="section-kicker">Deterministic authority</p>
        <h2 id="decision-title">Decision / containment</h2>
        <p className="panel-subtitle">Proposal, policy, approval, gateway, verification</p>
      </div>

      {isReplay ? (
        <div className="mode-notice mode-notice--replay" role="note">
          <span aria-hidden="true">◇</span>
          <div>
            <strong>{mode.simulation_notice}</strong>
            <p>{isEscalation ? "Live qualification failed; human escalation is required before any consequential review." : "No merchant-action controls are active in this mode. Recorded outcomes remain read-only."}</p>
          </div>
        </div>
      ) : null}

      <div className="decision-ledger" aria-label="Action lifecycle">
        {lifecycle.map((stage, index) => {
          const state = stageState(index, { proposal, policyDecision, approval, action, verification });
          return (
            <div className={`lifecycle-stage lifecycle-stage--${state}`} key={stage}>
              <span className="lifecycle-marker" aria-hidden="true">{state === "recorded" ? "✓" : state === "attention" ? "!" : "·"}</span>
              <span>{stage}</span>
              <small>{stageDetail(stage, { proposal, policyDecision, approval, action, verification })}</small>
            </div>
          );
        })}
      </div>

      {proposal ? (
        <div className="decision-section">
          <div className="section-title-row"><h3>Exact action packet</h3><span className="mono">{proposal.canonical_action_id ?? proposal.proposal_id}</span></div>
          <dl className="field-list">
            <Field label="Action" value={proposal.action_type} />
            <Field label="Target" value={proposal.target_resource} mono />
            <Field label="Amount / currency" value={proposal.amount_minor === null || proposal.amount_minor === undefined ? "Not applicable" : formatMinor(proposal.amount_minor, proposal.currency ?? "INR")} />
            <Field label="Reversibility" value={proposal.reversibility ?? "Not supplied"} />
            <Field label="Customer impact" value={proposal.customer_impact ?? "Not supplied"} />
            <Field label="Current resource state" value={proposal.current_resource_state ?? "Not supplied"} />
            <Field label="Proposer" value={proposal.proposer_id ?? "Not supplied"} mono />
          </dl>
          <div className="rationale-block"><span className="detail-label">Rationale</span><p>{proposal.rationale}</p></div>
          {!isReplay && !action && (approval?.status === "approved" || policyDecision?.result === "allow") ? (
            <div className="approval-actions">
              <button type="button" className="button button--primary consequential-command" disabled={busy} onClick={() => {
                setBusy(true);
                setMessage(null);
                void executeApprovedAction(tenantId, caseId, proposal.proposal_id)
                  .then(() => { setMessage("Action request recorded; refreshing authoritative state."); onRecorded?.(); })
                  .catch((error) => setMessage(error instanceof ReclaimApiError ? error.message : "The simulator action could not be submitted."))
                  .finally(() => setBusy(false));
              }}>{busy ? "Submitting to simulator…" : "Run approved action in simulator"}</button>
            </div>
          ) : null}
          {message ? <p className="command-message" role="status">{message}</p> : null}
        </div>
      ) : (
        <div className="empty-state empty-state--compact"><span className="empty-state__mark" aria-hidden="true">—</span><div><strong>No validated proposal</strong><p>Analysis has not produced a policy-bound action for this case.</p></div></div>
      )}

      <div className="decision-section policy-block">
        <div className="section-title-row"><h3>Policy result</h3><span className={`state-label state-label--${policyDecision?.result ?? "uncertain"}`}>{policyDecision?.result?.replaceAll("_", " ") ?? "Not evaluated"}</span></div>
        <dl className="field-list">
          <Field label="Policy version" value={policyDecision?.policy_version_id ?? "Not supplied"} mono />
          <Field label="Evaluator" value={policyDecision?.evaluator_version ?? "Not supplied"} mono />
          <Field label="Reason" value={policyDecision?.reason ?? "No policy reason supplied"} />
        </dl>
      </div>

      <div className={isUnknown ? "unknown-callout" : isInconclusive ? "unknown-callout unknown-callout--amber" : "next-decision"} role={isUnknown || isInconclusive ? "alert" : undefined}>
        <span className="unknown-callout__mark" aria-hidden="true">{isUnknown ? "?" : isInconclusive ? "!" : "→"}</span>
        <div>
          <span className="detail-label">Next human decision</span>
          <strong>{isUnknown ? "UNKNOWN — remote result unresolved. Reconciliation is required before retry." : isInconclusive ? "Verification is inconclusive — review escalation before any further action." : nextHumanDecision ?? "Review the authoritative case state."}</strong>
        </div>
      </div>
    </section>
  );
}

type LifecycleData = Pick<ActionDecisionPanelProps, "proposal" | "policyDecision" | "approval" | "action" | "verification">;

function stageState(index: number, data: LifecycleData): "recorded" | "attention" | "pending" {
  if (index === 0) return data.proposal ? "recorded" : "pending";
  if (index === 1) return data.policyDecision ? (data.policyDecision.result === "escalate" || data.policyDecision.result === "deny" ? "attention" : "recorded") : "pending";
  if (index === 2) return !data.approval || data.approval.status === "not_required" ? "recorded" : ["approved", "rejected", "expired", "revoked"].includes(data.approval.status) ? "recorded" : "attention";
  if (index === 3) return data.action ? data.action.status === "unknown" ? "attention" : "recorded" : "pending";
  if (index === 4) return data.action?.status === "unknown" ? "attention" : data.action?.reconciliation_state ? "recorded" : "pending";
  return data.verification ? data.verification.status === "inconclusive" ? "attention" : "recorded" : "pending";
}

function stageDetail(stage: string, data: LifecycleData): string {
  if (stage === "Policy evaluated") return data.policyDecision?.result?.replaceAll("_", " ") ?? "pending";
  if (stage === "Approval") return data.approval?.status?.replaceAll("_", " ") ?? "not required";
  if (stage === "Execution") return data.action?.status?.replaceAll("_", " ") ?? "not started";
  if (stage === "Reconciliation") return data.action?.reconciliation_state?.replaceAll("_", " ") ?? "not required";
  if (stage === "Verification") return data.verification?.status?.replaceAll("_", " ") ?? "pending";
  return data.proposal ? "recorded" : "pending";
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="field-item"><dt>{label}</dt><dd className={mono ? "mono" : undefined}>{value}</dd></div>;
}

function formatMinor(value: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(value / 100);
}
