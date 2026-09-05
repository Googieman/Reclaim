"use client";

import { useState } from "react";
import { ReclaimApiError, runReplay, type ModeAvailability, type ReplayResult } from "@/lib/api";

interface ReplayPanelProps {
  readonly tenantId: string;
  readonly caseId: string;
  readonly mode: ModeAvailability;
}

export function ReplayPanel({ tenantId, caseId, mode }: ReplayPanelProps) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ReplayResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function simulate() {
    setRunning(true);
    setMessage(null);
    try {
      const replay = await runReplay(tenantId, { caseId, deterministicSeed: 0 });
      setResult(replay);
    } catch (error) {
      setMessage(error instanceof ReclaimApiError ? error.message : "The simulation could not be started.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="subpanel replay-panel" aria-labelledby="replay-title">
      <div className="subpanel-heading"><div><p className="section-kicker">Recorded path</p><h3 id="replay-title">Replay / simulation</h3></div><span className="state-label state-label--replay">REPLAY</span></div>
      <p className="panel-copy">Provider availability: {mode.provider_available ? "available" : "unavailable"}. Connector availability: {mode.connector_available ? "available" : "unavailable"}. Replay is always labeled and has no merchant side effects.</p>
      <dl className="provenance-grid">
        <div><dt>Requested</dt><dd>{mode.requested_mode}</dd></div>
        <div><dt>Effective</dt><dd>{mode.effective_mode}</dd></div>
        <div><dt>Final</dt><dd>{mode.final_mode}</dd></div>
        <div><dt>Decision version</dt><dd className="mono">{mode.decision_version}</dd></div>
      </dl>
      <button type="button" className="button button--primary" onClick={simulate} disabled={running}>{running ? "Running simulated path…" : "Run simulated replay"}</button>
      {message ? <p className="command-message" role="alert">{message}</p> : null}
      {result ? <div className="replay-result" role="status"><strong>Recorded replay result</strong><span className="mono">{result.run_id ?? "run identity not supplied"}</span><span>{result.terminal_state ?? "Terminal state not supplied"}</span><span className="state-label state-label--replay">No remote side effects</span></div> : null}
    </section>
  );
}
