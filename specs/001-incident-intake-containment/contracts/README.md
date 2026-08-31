# FS-001 Boundary Contracts

These contracts define data and authority boundaries for implementation and testing. They are language-neutral and versioned. Concrete serializers, generated types, authentication middleware, and migrations belong to implementation tasks and must not change the ownership rules here without an ADR.

## Contract principles

- Every request, event, tool call, decision, and audit record carries `tenant_id` and correlation identifiers.
- Every contract declares schema version, producer, timestamp semantics, and idempotency identity where applicable.
- Evidence and model output are untrusted/advisory; only deterministic validators and policy can authorize action.
- Webhook case/incident association is authoritative only when a verified provider
  correlation resolves through PostgreSQL; caller-supplied IDs are consistency
  assertions and never mapping authority.
- Simulators implement the same contract and allowlist as live connectors.
- Unknown remote result is a first-class state, never an implicit failure or success.

See [intake-webhook.md](./intake-webhook.md), [connectors.md](./connectors.md), [events.md](./events.md), [analysis-policy.md](./analysis-policy.md), [action-gateway.md](./action-gateway.md), and [audit-replay.md](./audit-replay.md).
