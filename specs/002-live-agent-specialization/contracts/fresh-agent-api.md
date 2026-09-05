# Fresh-Agent API Contract

## Start fresh analysis

`POST /tenants/{tenant_id}/cases/{case_id}/agent-runs`

Request:

```json
{
  "provider_profile": "reclaim-specialist",
  "fallback_policy": "explicit_unavailable",
  "budget": {
    "max_tokens": 2048,
    "max_tool_calls": 4,
    "timeout_seconds": 60
  }
}
```

The body is strict. The route derives tenant/case identity from the path and obtains the bounded case context from the existing deterministic analysis/read model. It does not accept credentials, raw model prompts, arbitrary endpoint URLs, action commands, or approval commands.

Response (`202` for an asynchronous coordinator or `200` for a completed local demo run):

```json
{
  "run_id": "agent-run-...",
  "tenant_id": "tenant-...",
  "case_id": "case-...",
  "correlation_id": "correlation-...",
  "execution_mode": "fresh_agent",
  "action_environment": "simulator",
  "profile": "reclaim-specialist",
  "provider": "openai-compatible-local",
  "model": "...",
  "status": "completed",
  "analysis": {
    "analysis_id": "analysis-...",
    "attributions": [],
    "uncertainty": "...",
    "proposals": []
  },
  "proposal_validation": {"status": "accepted", "side_effects": false},
  "policy_result": null,
  "error": null,
  "provenance": {
    "prompt_version": "...",
    "harness_version": "...",
    "request_checksum": "...",
    "response_checksum": "..."
  }
}
```

The response never contains hidden reasoning. Proposal validation is advisory-boundary validation only; action policy, approval, Action Gateway execution, reconciliation, verification, and audit remain separate.

## Read fresh run

`GET /tenants/{tenant_id}/cases/{case_id}/agent-runs/{run_id}` returns the same response shape, filtered to the tenant/case scope. Unknown or cross-scope runs return `404`/`403` according to the existing API authorization convention.

## Failure semantics

- `409`: invalid case/mode/profile or deterministic proposal rejection where the request cannot be accepted.
- `503`: configured model unavailable or endpoint unreachable; body status is `unavailable` and does not contain a replay result.
- `422`: malformed strict request or invalid budget.
- `200/202` with `failed`, `rejected`, `deterministic_only`, or `escalation_required`: explicit run outcome where the coordinator completed its bounded handling.

## Mode separation

The replay endpoint remains `/tenants/{tenant_id}/cases/{case_id}/replay` and keeps `mode: replay`, `label: replay`, and no fresh provider call. `execution_mode: fresh_agent` means model execution only; `action_environment` separately identifies simulator, Test Mode, or live merchant connector. No endpoint auto-approves or executes a proposal.
