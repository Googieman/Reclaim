# RECLAIM US1 final review architecture map

Review scope: FS-001 User Story 1, T001-T058, including remediation batches A-C,
the MAJOR-7 approval/execution closure, and the T043 fixture-isolation repair.
T059 and US2 were not started. This is a read-only review performed on 2026-08-31.

## Governing ownership

- PostgreSQL is the authoritative store for business state, aggregate relationships,
  policy/approval/action integrity, audit records, outbox, and inbox delivery state.
- Temporal owns durable orchestration and retry/recovery. The CaseWorkflow re-reads
  PostgreSQL state and does not substitute workflow state for business truth.
- Redpanda is at-least-once transport. Consumers require authenticated service
  context, tenant binding, producer/service allowlists, and exact PostgreSQL outbox
  reconciliation before handler mutation.
- Neo4j is a tenant-scoped, rebuildable relationship projection. PostgreSQL inbox
  state is the delivery idempotency boundary; Neo4j checkpoints are non-authoritative.
- MinIO stores immutable raw evidence/report objects with tenant-scoped keys and
  checksums. Redis is bounded coordination/cache/rate-limit state only.
- Keycloak/OIDC supplies signed tenant-role bindings; Vault paths and callers are
  scoped by connector/service. No financial/account mutation or model inference is
  implemented through T058.

## Trust boundaries reviewed

HTTP/authentication and webhook bytes; connector responses and replay fixtures;
Temporal commands/signals/activity results; Redpanda envelopes and malformed broker
messages; PostgreSQL RLS/UoW/repository and migration constraints; MinIO object
creation/read references; Neo4j projection and rebuild input; Redis locks; packaging
and development configuration.

## Prior work considered

The repository contains a pre-existing `security-audits/foundation-t035` audit but no
standalone prior US1 Engineering Review document. Prior US1 remediation claims were
reconstructed from `PROJECT_STATUS.md`, the specified commits, current source, tests,
and `docs/validation/us1-intake-timeline.md`.

The following commits were specifically reviewed: `b61c330`, `4d5dead`,
`72e373746dd316aca8d0aed3200e9838b985e73c`, `40e397dc1c23da33b94d94f5b3c62e83be86953f`,
and `45026982a906584d1b70c509fb48769203eeb2b1`.

## Review conclusion

The current US1 path has strong tenant, authority, provenance, deterministic ordering,
payload, immutable-object, workflow, event-reconciliation, and packaging controls.
Two newly confirmed current-gate majors remain, and MAJOR-5 is only partially
remediated:

1. the audit chain permits multiple concurrent null-predecessor roots for a tenant;
2. timeline uncertainty is computed in memory but omitted from the persisted timeline
   representation and the production `timeline.rebuilt` outbox payload.
3. the webhook processor rejects cross-tenant and mismatched pair substitutions, but
   still accepts a caller-selected same-tenant case when no authoritative provider-to-
   case correlation is supplied.

These findings keep T059 blocked until repaired and covered by direct association,
concurrency, and uncertainty-propagation tests.
