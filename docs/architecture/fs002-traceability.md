# FS-002 traceability

The live-agent specialization slice reuses the approved FS-001 architecture.

| Boundary | Implementation | Safety property |
| --- | --- | --- |
| Model context | `backend/agent/redaction.py`, `backend/agent/prompts.py` | Redacted, bounded, untrusted evidence; deterministic financial authority |
| Provider | `backend/agent/litellm_gateway.py`, `backend/agent/model_profiles.py` | Allowlisted profile and endpoint; credentials stay in transport |
| Agent runtime | `backend/agent/fresh_run.py`, existing LangGraph harness | Strict parser, typed proposals, no side-effect channel |
| Orchestration | `backend/workflows/activities/agent_analysis.py` | Optional Temporal activity with service identity and tenant/case checks |
| Data | `training/reclaim/scripts/` | Deterministic labels, frozen grouped/time split, sealed held-out metadata |
| Operator surface | `backend/api/agent_runs.py`, `frontend/src/components/agent/` | Fresh and replay labels remain separate; no automatic action control |

The local `AgentRunStore` is a read cache for the no-Postgres demonstration only.
The API accepts an optional typed persistence callback for production wiring; it
receives the redacted `AgentRun` after strict parsing and before the response is
returned. Case, policy, approval, action, verification, and audit authority remain
in their existing PostgreSQL/Temporal/Action Gateway paths. A production deployment
must inject the existing PostgreSQL model-analysis persistence transaction before
promoting this route beyond local/test use.
