# US1 intake-to-timeline validation evidence

Validation date: 2026-08-30

Status: passed in a local, dependency-safe live validation run. This is not a
production fraud, containment, or provider-performance claim.

## Gate

Command:

```text
python -m pytest tests/integration/test_us1_vertical_slice.py -q
```

Observed result: `1 passed in 5.22s` with the test-only environment configured
for the temporary services listed below.

The Remediation Batch A rerun uses the authenticated `CaseWorkflowCommandService`
and the production `create_case_worker` registration. The canonical case therefore
executes the real `case.collect_evidence` activity and persisted-evidence
`case.rebuild_timeline` activity; the workflow performs a final authoritative
PostgreSQL state read and the gate verifies `timeline_ready`. The rerun also verifies
the immutable MinIO incident-report object and checksum-linked PostgreSQL incident
and audit references.

The gate used a newly generated tenant and a separate boundary tenant. It
proved authenticated tenant-bound intake, duplicate intake idempotency,
cross-tenant HTTP denial, Razorpay Test Mode-compatible HMAC authenticity and
duplicate handling, invalid webhook quarantine, incident/case creation,
Temporal workflow control, evidence collection, MinIO checksum verification,
PostgreSQL persistence, deterministic timeline reconstruction, transactional
outbox emission, Redpanda delivery, Neo4j projection and rebuild, duplicate
projection delivery, cross-tenant projection denial, audit-chain continuity,
and partial/unavailable evidence behavior.

The evidence connectors in this run were deterministic simulator connectors.
Their evidence and provider fixtures are explicitly replay-labeled and must
not be presented as live merchant-provider evidence. The Razorpay check used a
test-only local signing secret and did not call Razorpay.

Before Redpanda delivery, the authoritative PostgreSQL counts for the gate
tenant were observed as:

| incidents | cases | evidence items | timeline events | outbox events | audit records |
|---:|---:|---:|---:|---:|---:|
| 2 | 2 | 8 | 7 | 13 | 6 |

All 13 outbox rows were acknowledged by Redpanda. Twelve US1 projection events
were applied because the valid webhook is intentionally not a projection
family. Replaying a delivered event was a no-op through the PostgreSQL inbox;
rebuilding Neo4j from reversed event order applied the same 12 events. The
PostgreSQL incident count remained `2` after projection reset/rebuild.

## Services used

These were temporary Docker services, not a deployed production topology:

| service | image/version | local endpoint |
|---|---|---|
| PostgreSQL | `postgres:16-alpine` | `localhost:55432` |
| MinIO | `minio:RELEASE.2024-12-18T13-15-44Z` | `localhost:59000` (API), `59001` (console) |
| Redpanda | `redpandadata/redpanda:v24.3.6` | `localhost:59092` (Kafka), `59644` (admin) |
| Neo4j | `neo4j:5.26-community` | `bolt://localhost:57687`, HTTP `57474` |
| Temporal | `temporalio/auto-setup:1.27.2` | `localhost:57233` |

## Independent checks

- Redpanda real producer/consumer validation: `4 passed in 0.48s`.
- Neo4j case/evidence/timeline projection, reset, and live rebuild: `4 passed in 1.33s`.
- Live PostgreSQL foundation commit/rollback and inbox/outbox checks: `2 passed in 0.57s`.
- Existing T043 acceptance against live PostgreSQL and MinIO: `4 passed in 1.40s`.

PostgreSQL remains authoritative for incident, case, evidence, timeline,
outbox, inbox, and audit state. Redpanda is transport only. Neo4j stores a
rebuildable relationship projection and checkpoint metadata; reset or loss of
that projection does not modify PostgreSQL truth. Event consumers require an
authenticated service context and reject tenant-mismatched envelopes.
