# Fresh-agent analysis

Fresh analysis is an opt-in, tenant/case-scoped model run. It is distinct from
the deterministic REPLAY surface:

- `fresh_agent` calls the configured provider through the existing LangGraph and
  LiteLLM adapter, then accepts only the strict typed analysis response.
- `replay` runs the canonical deterministic fixture and is never substituted into
  a fresh run when the provider is unavailable.
- Both paths are advisory. Neither grants policy approval, executes an Action
  Gateway command, changes a merchant account, or bypasses verification.

Enable the local route only in a non-production process:

```powershell
$env:RECLAIM_FRESH_AGENT_ENABLED = "true"
$env:RECLAIM_FRESH_AGENT_PROFILE = "reclaim-specialist"
$env:RECLAIM_SPECIALIST_MODEL = "<observed-local-model-id>"
$env:RECLAIM_SPECIALIST_API_BASE = "http://127.0.0.1:8003/v1"
```

Then call:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/tenants/tenant-canonical-demo/cases/case-canonical-demo-001/agent-runs" `
  -ContentType "application/json" -Body '{}'
```

The response includes the fresh execution mode, profile, provider/model, prompt/
parser versions, checksums, observed token/cost fields, and the typed advisory
analysis. An unavailable provider is returned as an explicit unavailable result;
it is not relabeled as live or replay.

For a production integration, pass a persistence callback from the application’s
PostgreSQL model-analysis transaction. The callback receives the redacted typed
`AgentRun`; raw provider output, hidden reasoning, credentials, and execution
handles are not part of this boundary.
