# FS-001 Architecture and authority boundaries

FS-001 implements the approved RECLAIM architecture through vertical slices. As of
the 2026-09-03 governance amendment, n8n is the project-wide durable orchestrator for
new work. The application service layer is orchestrator-neutral; Temporal is retained
only in the legacy drain profile until existing runs finish.

## Authority

- PostgreSQL is authoritative for tenant, case, evidence metadata, timeline, attribution,
  exposure, policy, approval, action, verification, escalation, audit, replay, and
  evaluation state.
- n8n owns durable orchestration, retries, and recovery for new work. It receives only
  a tenant-scoped service identity and calls allowlisted, idempotent RECLAIM APIs.
- Temporal is a legacy drain path and MUST NOT receive new incidents.
- Redpanda transports versioned events through transactional outbox/inbox handling; it is
  not business authority. Consumers require an authenticated allowlisted service,
  allowlisted producer, supported schema/checksum, and exact PostgreSQL outbox
  reconciliation before any downstream projection write.
- Neo4j is a rebuildable relationship projection.
- MinIO stores immutable raw evidence and artifacts addressed by checksum.
- Redis is n8n queue coordination plus bounded cache/locks/rate limiting. It is never
  RECLAIM business authority.

## n8n boundary

- The Kafka Trigger consumes the versioned `incident.accepted` envelope from Redpanda.
- Each execution claims its run with the n8n execution ID. RECLAIM persists the
  authoritative `orchestration_runs` and `orchestration_stage_attempts` records in
  PostgreSQL; n8n execution history is operational metadata only.
- Workflow nodes may call normalization, typed analysis, deterministic validation,
  policy, and human-handoff APIs. Stages are allowlisted and require expected-state
  and idempotency values.
- n8n has no direct PostgreSQL, MinIO, model-provider, approval, or Action Gateway
  credentials. Failures become `requires_attention`; replay is never an implicit
  recovery action.
- Raw narratives and sensitive evidence are stored in immutable MinIO objects and are
  represented in events/logs by identifiers, metadata, and checksums only.

## Safety boundary

The model receives redacted structured evidence and typed read/proposal interfaces only.
It has no action credentials, database-write authority, shell access, arbitrary network
access, or direct connector access. Typed proposals pass deterministic validation,
versioned policy, required independent approval, stable idempotency, the isolated Action
Gateway, verification, and append-only audit before any merchant-controlled mutation.
Live financial execution remains disabled by default.

## Source decisions

- [ADR-001](../../specs/001-incident-intake-containment/decisions/ADR-001-authoritative-ownership.md)
  defines authoritative ownership and projection boundaries.
- [ADR-002](../../specs/001-incident-intake-containment/decisions/ADR-002-isolated-action-boundary.md)
  defines the bounded model and Action Gateway boundary.
- [ADR-003](../../specs/001-incident-intake-containment/decisions/ADR-003-replay-evaluation-baselines.md)
  defines labeled replay, grouped evaluation, and honest baselines.
- [ADR-004](../../specs/001-incident-intake-containment/decisions/ADR-004-n8n-orchestration-boundary.md)
  supersedes ADR-001's Temporal ownership for new work and defines the n8n migration
  and drain boundary.
- [Feature specification](../../specs/001-incident-intake-containment/spec.md),
  [plan](../../specs/001-incident-intake-containment/plan.md), and
  [tasks](../../specs/001-incident-intake-containment/tasks.md) are the governing FS-001
  artifacts.
