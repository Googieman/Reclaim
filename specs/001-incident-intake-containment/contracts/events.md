# Event Envelope and Delivery Contract

Required envelope fields: `event_id`, `schema_version`, `event_type`, `tenant_id`, `aggregate_type`, `aggregate_id`, `occurred_at`, `produced_at`, `correlation_id`, `causation_id`, producer, payload checksum, and payload.

## Delivery rules

- Producers write business state and outbox record in one PostgreSQL transaction.
- Redpanda delivery is at-least-once; consumers must use tenant-aware inbox identity and be idempotent.
- Ordering is not assumed globally; domain reconstruction uses event timestamps and stable tie-breakers.
- Consumers acknowledge only after authoritative state/projection handling is complete for their responsibility.
- Neo4j consumers may rebuild from authoritative events; failure does not block PostgreSQL correctness.

## Event families

`incident.accepted`, `webhook.quarantined`, `evidence.collected`, `timeline.rebuilt`, `attribution.completed`, `exposure.calculated`, `proposal.created`, `policy.decided`, `approval.recorded`, `action.requested`, `action.unknown`, `action.reconciled`, `verification.completed`, `case.escalated`, `case.terminal`.
