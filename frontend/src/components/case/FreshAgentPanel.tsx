"use client";

import { useState } from "react";
import { ReclaimApiError, runFreshAgent, type AgentAnalysis, type FreshAgentRun } from "@/lib/api";
import { AgentRunBadge } from "@/components/agent/AgentRunBadge";

interface FreshAgentPanelProps {
  readonly tenantId: string;
  readonly caseId: string;
  readonly persistedAnalysis?: AgentAnalysis | null;
  readonly onRecorded?: () => void;
}

export function FreshAgentPanel({ tenantId, caseId, persistedAnalysis, onRecorded }: FreshAgentPanelProps) {
  const [run, setRun] = useState<FreshAgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function startRun() {
    setBusy(true);
    setMessage(null);
    try {
      setRun(await runFreshAgent(tenantId, { caseId }));
      onRecorded?.();
    } catch (error) {
      setRun(null);
      setMessage(error instanceof ReclaimApiError ? error.message : "The fresh model run could not be started.");
    } finally {
      setBusy(false);
    }
  }

  const analysis = run?.analysis;
  return (
    <section className="subpanel fresh-agent-panel" aria-labelledby="fresh-agent-title">
      <div className="subpanel-heading">
        <div><p className="section-kicker">Model run</p><h3 id="fresh-agent-title">Fresh agent analysis</h3></div>
        <span className="state-label state-label--live">LIVE-LABELLED</span>
      </div>
      <p className="panel-copy">Runs the configured bounded model through LangGraph and LiteLLM. This is separate from REPLAY and produces advisory proposals only.</p>
      <div className="fresh-agent-boundary" role="note">
        <strong>No remote merchant effects</strong>
        <span>Policy, approval, Action Gateway, and verification remain separate.</span>
      </div>
      <button type="button" className="button button--primary" disabled={busy} onClick={() => void startRun()}>
        {busy ? "Running fresh model…" : "Run fresh agent"}
      </button>
      {message ? <p className="command-message" role="alert">{message}</p> : null}
      {persistedAnalysis ? <PersistedAnalysis analysis={persistedAnalysis} /> : run ? (
        <div className="fresh-agent-result" role="status">
          <div className="section-title-row"><AgentRunBadge run={run} /><span className="mono">{run.run_id}</span></div>
          <dl className="provenance-grid">
            <div><dt>Profile</dt><dd className="mono">{run.profile}</dd></div>
            <div><dt>Provider / model</dt><dd className="mono">{run.provider ?? "Unavailable"} / {run.model ?? "—"}</dd></div>
            <div><dt>Prompt / parser</dt><dd className="mono">{run.provenance.prompt_version} / {run.provenance.parser_version}</dd></div>
            <div><dt>Execution</dt><dd>{run.provenance.fresh_execution_observed ? "Observed" : "Not observed"} · {run.action_environment}</dd></div>
          </dl>
          {analysis ? (
            <>
              <div className="fresh-agent-summary"><span className="detail-label">Uncertainty</span><p>{analysis.uncertainty}</p></div>
              <div className="fresh-agent-summary"><span className="detail-label">Attributions</span><p>{analysis.attributions.length} typed timeline attribution{analysis.attributions.length === 1 ? "" : "s"} · {analysis.proposals.length} advisory proposal{analysis.proposals.length === 1 ? "" : "s"}</p></div>
            </>
          ) : <p className="panel-copy">{run.error ?? "No parsed analysis was returned."}</p>}
          <span className="state-label state-label--legitimate">No remote side effects recorded</span>
        </div>
      ) : null}
    </section>
  );
}

function PersistedAnalysis({ analysis }: { analysis: AgentAnalysis }) {
  return (
    <div className="fresh-agent-result" role="status">
      <div className="section-title-row"><strong>Authoritative analysis · {analysis.status}</strong><span className="mono">{analysis.analysis_id}</span></div>
      <dl className="provenance-grid">
        <div><dt>Run</dt><dd className="mono">{analysis.run_id ?? "Not linked"}</dd></div>
        <div><dt>Provider / model</dt><dd className="mono">{analysis.provider ?? "Unavailable"} / {analysis.model ?? "—"}</dd></div>
        <div><dt>Authority</dt><dd className="mono">{analysis.provenance.authoritative_store}</dd></div>
        <div><dt>Deterministic checksums</dt><dd className="mono">{analysis.provenance.deterministic_analysis_checksum} · {analysis.provenance.deterministic_exposure_checksum}</dd></div>
      </dl>
      <div className="fresh-agent-summary"><span className="detail-label">Uncertainty</span>{analysis.uncertainty.length ? <ul>{analysis.uncertainty.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>No uncertainty recorded.</p>}</div>
      <div className="fresh-agent-summary"><span className="detail-label">Typed result</span><p>{analysis.attributions.length} timeline attribution{analysis.attributions.length === 1 ? "" : "s"} · {analysis.refusal_records.length} refusal record{analysis.refusal_records.length === 1 ? "" : "s"}</p></div>
      <span className="state-label state-label--legitimate">Read from PostgreSQL authoritative state</span>
    </div>
  );
}
