"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { ActionDecisionPanel } from "@/components/case/ActionDecisionPanel";
import { ApprovalPanel } from "@/components/case/ApprovalPanel";
import { CaseTimeline } from "@/components/case/CaseTimeline";
import { EscalationPanel } from "@/components/case/EscalationPanel";
import { ExposureSummary } from "@/components/case/ExposureSummary";
import { FreshAgentPanel } from "@/components/agent/FreshAgentPanel";
import { AuditTrace } from "@/components/audit/AuditTrace";
import { ModeBadge } from "@/components/replay/ModeBadge";
import { ReplayPanel } from "@/components/replay/ReplayPanel";
import { AppNavigation } from "@/components/navigation/AppNavigation";
import { getCase, getModeAvailability, ReclaimApiError, seedDemoCase, type ModeAvailability, type OperatorCaseView } from "@/lib/api";
import { getFrontendConfig } from "@/lib/config";

const config = getFrontendConfig();

export default function CasePage() {
  const params = useParams<{ caseId: string | string[] }>();
  const caseId = Array.isArray(params.caseId) ? params.caseId[0] : params.caseId;
  const [view, setView] = useState<OperatorCaseView | null>(null);
  const [mode, setMode] = useState<ModeAvailability | null>(null);
  const [error, setError] = useState<ReclaimApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [auditAnchor, setAuditAnchor] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const loadAuthoritativeView = useCallback(async ({ background = false }: { background?: boolean } = {}) => {
    if (!caseId) return;
    const requestId = ++requestSequence.current;
    if (background) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const [nextView, nextMode] = await Promise.all([
        getCase(config.tenantId, caseId),
        getModeAvailability(config.tenantId),
      ]);
      if (requestId !== requestSequence.current) return;
      setView(nextView);
      setMode(nextMode);
    } catch (reason) {
      if (requestId !== requestSequence.current) return;
      setError(reason instanceof ReclaimApiError ? reason : new ReclaimApiError("The authoritative case view could not be loaded.", "network"));
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [caseId]);

  useEffect(() => {
    const loadTask = window.setTimeout(() => void loadAuthoritativeView(), 0);
    // The case identity is the only input that changes the authority scope.
    return () => window.clearTimeout(loadTask);
  }, [caseId, loadAuthoritativeView]);

  if (loading) return <LoadingWorkspace />;
  if (!view || !mode) return <UnavailableWorkspace tenantId={config.tenantId} caseId={caseId} error={error} onRetry={() => void loadAuthoritativeView()} />;

  const caseRecord = view.case;
  const nextDecision = view.next_human_decision ?? "Review the authoritative case state.";
  const readOnly = view.read_only || mode.final_mode !== "live";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#investigation">Skip to investigation</a>
      <a className="skip-link" href="#decision">Skip to decision</a>
      <a className="skip-link" href="#audit">Skip to audit</a>
      <AppNavigation tenantId={caseRecord.tenant_id} />

      <div className="main-column">
        <header className="top-bar">
          <div className="top-bar__identity"><span className="mobile-brand-mark" aria-hidden="true">R</span><span>Incident command</span></div>
          <div className="top-bar__context"><span className="context-label">Merchant</span><strong>{caseRecord.merchant_name ?? "Demo merchant"}</strong><span className="context-divider" aria-hidden="true" /><ModeBadge mode={mode} compact /><span className="environment-label">{environmentLabel(mode)}</span></div>
          <div className="operator-identity"><span className="operator-dot" aria-hidden="true" />Reviewer session</div>
        </header>

        <section className="case-header" aria-labelledby="case-title">
          <div>
            <p className="section-kicker">Case review</p>
            <h1 id="case-title">{caseRecord.case_id}</h1>
            <p className="case-context">{caseRecord.merchant_name ?? "Demo merchant"}{caseRecord.incident_id ? ` · incident ${caseRecord.incident_id}` : ""}</p>
          </div>
          <div className="case-header__facts">
            <Fact label="State" value={caseRecord.state.replaceAll("_", " ")} />
            <Fact label="Owner" value={caseRecord.owner_id ?? "Unassigned"} mono />
            <Fact label="Severity" value={caseRecord.severity ?? "Not classified"} />
            <Fact label="Automation" value={view.orchestration ? view.orchestration.status.replaceAll("_", " ") : "Not started"} />
            <Fact label="Workflow" value={view.orchestration?.workflow_version ?? "Not started"} mono />
            <Fact label="Last authoritative refresh" value={caseRecord.last_refreshed_at ?? view.data_as_of ?? "Not supplied"} mono />
            <ModeBadge mode={mode} />
          </div>
        </section>

        <div className="workspace-notice" role="status" aria-live="polite">
          <span aria-hidden="true">◌</span>
          <span>{view.authoritative ? "Authoritative case view" : "Replay fixture view — not authoritative merchant state"} · {mode.label === "fresh_agent" ? "Fresh Agent + Action Gateway Simulator/Test Mode — no live merchant effects" : "tenant-scoped · financial values are read-only"}</span>
          {view.evaluation ? <span className="workspace-notice__evaluation">Evaluation: {view.evaluation.label} · fixture {view.evaluation.fixture_version}</span> : null}
          {refreshing ? <span className="workspace-notice__evaluation">Refreshing authoritative state…</span> : null}
          {error ? <span className="workspace-notice__evaluation">Refresh unavailable: {error.message}</span> : null}
        </div>

        <main className="workspace">
          <section className="investigation-column" aria-label="Incident investigation workspace">
            <ReportedIncidentPanel incident={view.reported_incident} orchestration={view.orchestration} />
            <CaseTimeline events={view.timeline} onOpenAudit={setAuditAnchor} />
          </section>
          <aside className="decision-column" aria-label="Decision and containment workspace">
            <ExposureSummary exposure={view.exposure} />
            <ActionDecisionPanel tenantId={caseRecord.tenant_id} caseId={caseRecord.case_id} proposal={view.proposal} policyDecision={view.policy_decision} approval={view.approval} action={view.action} verification={view.verification} mode={mode} onRecorded={() => void loadAuthoritativeView({ background: true })} nextHumanDecision={nextDecision} />
            <ApprovalPanel tenantId={caseRecord.tenant_id} approval={view.approval} proposal={view.proposal} policyDecision={view.policy_decision} readOnly={readOnly} onRecorded={() => void loadAuthoritativeView({ background: true })} />
            <EscalationPanel tenantId={caseRecord.tenant_id} escalation={view.escalation} readOnly={readOnly} onRecorded={() => void loadAuthoritativeView({ background: true })} />
            <FreshAgentPanel tenantId={caseRecord.tenant_id} caseId={caseRecord.case_id} persistedAnalysis={view.agent_analysis} onRecorded={() => void loadAuthoritativeView({ background: true })} />
            <ReplayPanel tenantId={caseRecord.tenant_id} caseId={caseRecord.case_id} mode={mode} />
          </aside>
        </main>

        <AuditTrace records={view.audit} anchor={auditAnchor} />
      </div>
    </div>
  );
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="case-fact"><span>{label}</span><strong className={mono ? "mono" : undefined}>{value}</strong></div>;
}

function ReportedIncidentPanel({ incident, orchestration }: { incident: OperatorCaseView["reported_incident"]; orchestration: OperatorCaseView["orchestration"] }) {
  if (!incident && !orchestration) return null;
  return (
    <section className="panel reported-incident-panel" aria-labelledby="reported-incident-title">
      <div className="panel-heading"><div><p className="section-kicker">Intake record</p><h2 id="reported-incident-title">Reported incident</h2><p className="panel-subtitle">Typed intake metadata · reported value remains unverified.</p></div>{orchestration ? <span className="mode-badge mode-badge--compact">{orchestration.status.replaceAll("_", " ")}</span> : null}</div>
      {incident ? <dl className="reported-incident-grid"><div><dt>Type</dt><dd>{humanize(incident.incident_type)}</dd></div><div><dt>Source</dt><dd>{incident.source}</dd></div><div><dt>Occurred</dt><dd className="mono">{incident.occurred_at}</dd></div><div><dt>Reported value</dt><dd>{formatReportedAmount(incident.reported_amount_minor, incident.reported_currency)}</dd></div><div><dt>References</dt><dd>{referenceSummary(incident)}</dd></div><div><dt>Evidence</dt><dd className="mono">{incident.narrative_checksum ?? incident.report_reference ?? "Stored in immutable evidence"}</dd></div></dl> : null}
      {orchestration?.failure_code ? <p className="unknown-callout unknown-callout--amber"><span className="unknown-callout__mark" aria-hidden="true">!</span><span><strong>Human attention required</strong>Automation recorded {orchestration.failure_code}; no replay or action was substituted.</span></p> : null}
    </section>
  );
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function referenceSummary(incident: NonNullable<OperatorCaseView["reported_incident"]>) {
  const refs = [incident.customer_reference, incident.account_reference, incident.order_reference, incident.payment_reference, incident.external_reference].filter(Boolean);
  return refs.length ? refs.join(" · ") : "No references supplied";
}

function formatReportedAmount(amount: number | null | undefined, currency: string | null | undefined) {
  if (amount === null || amount === undefined || !currency) return "Not supplied";
  const units = ["BHD", "KWD"].includes(currency) ? 3 : ["CLP", "JPY", "KRW", "VND"].includes(currency) ? 0 : 2;
  return `${new Intl.NumberFormat("en", { style: "currency", currency, minimumFractionDigits: units, maximumFractionDigits: units }).format(amount / 10 ** units)} · unverified`;
}

function environmentLabel(mode: ModeAvailability): string {
  if (mode.label === "fresh_agent") return "FRESH AGENT · SIMULATOR";
  if (mode.final_mode === "live") return "SERVER-QUALIFIED ENVIRONMENT";
  if (mode.final_mode === "escalation") return "ESCALATION STATE";
  return "SERVER-QUALIFIED SIMULATION";
}

function LoadingWorkspace() {
  return <main className="loading-workspace" aria-busy="true" aria-label="Loading authoritative case workspace"><div className="loading-header skeleton-line" /><div className="loading-grid"><div className="panel skeleton-panel" /><div className="panel skeleton-panel" /></div><div className="panel skeleton-trace" /></main>;
}

function UnavailableWorkspace({ tenantId, caseId, error, onRetry }: { tenantId: string; caseId: string; error: ReclaimApiError | null; onRetry: () => void }) {
  const [seeding, setSeeding] = useState(false);
  const [seedMessage, setSeedMessage] = useState<string | null>(null);
  const title = error?.kind === "permission" ? "Case access is not authorized" : error?.kind === "missing" ? "Case not found" : "Authoritative case view unavailable";
  const copy = error?.kind === "permission" ? "The session does not have reviewer access to this tenant scope." : error?.message ?? "No authoritative read model was returned. Consequential controls are withheld.";
  async function seed() {
    setSeeding(true);
    setSeedMessage(null);
    try {
      await seedDemoCase(tenantId, caseId);
      onRetry();
    } catch (reason) {
      setSeedMessage(reason instanceof ReclaimApiError ? reason.message : "The synthetic case could not be created.");
    } finally {
      setSeeding(false);
    }
  }
  return <main className="unavailable-workspace"><div className="unavailable-mark" aria-hidden="true">!</div><p className="section-kicker">Local authoritative demo</p><h1>{title}</h1><p>{copy}</p><div className="unavailable-actions"><button type="button" className="button button--primary" disabled={seeding} onClick={() => void seed()}>{seeding ? "Creating synthetic case…" : "Create / load synthetic case"}</button><button type="button" className="button button--quiet" onClick={onRetry}>Try authoritative read again</button></div>{seedMessage ? <p className="command-message" role="alert">{seedMessage}</p> : null}</main>;
}
