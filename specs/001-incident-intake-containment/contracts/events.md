# Event Envelope and Delivery Contract

Required envelope fields: `event_id`, `schema_version`, `event_type`, `tenant_id`, `aggregate_type`, `aggregate_id`, `occurred_at`, `produced_at`, `correlation_id`, `causation_id`, producer, payload checksum, and payload.

## Webhook-derived payload semantics

The shared event-envelope schema remains `1.0.0`; the D3 change is a required payload
semantics update for webhook-derived records and does not change event ownership.

When an accepted webhook delivery is represented in an outbox or domain event, its
payload MUST carry:

- `verified_provider_correlation` at schema version `1.0.0`, including provider,
  configured connector, provider event ID, required provider payment/order identifier,
  verification state/provenance, verifier version, and original payload checksum;
- `authoritative_mapping_id` and `association_status=resolved`; and
- `tenant_id`, `incident_id`, and `case_id` values returned by the PostgreSQL mapping,
  with related order/payment context where applicable.

The event payload MUST NOT promote caller-supplied tenant, merchant, incident, case, or
transport correlation values into these authoritative fields. `incident.accepted`
events originating from an operator report remain valid without provider correlation;
only events derived from a webhook require these fields.

For `webhook.quarantined`, a verified correlation may be included when authenticity
succeeded, together with `association_status` such as `unresolved_association`,
`mapping_conflict`, `cross_tenant`, or `assertion_mismatch`. The payload MUST omit
authoritative incident/case association when the event is quarantined. Invalid or
unverifiable deliveries may omit the correlation object entirely.

Replay and live producers use these identical payload rules and versions. Redpanda
remains transport only; consumers must not infer a case from an event ID or caller
field when the mapping reference is absent.

## Delivery rules

- Producers write business state and outbox record in one PostgreSQL transaction.
- Redpanda delivery is at-least-once; consumers must use tenant-aware inbox identity and be idempotent.
- Ordering is not assumed globally; domain reconstruction uses event timestamps and stable tie-breakers.
- Consumers acknowledge only after authoritative state/projection handling is complete for their responsibility.
- Neo4j consumers may rebuild from authoritative events; failure does not block PostgreSQL correctness.

## Event families

`incident.accepted`, `webhook.quarantined`, `evidence.collected`, `timeline.rebuilt`, `attribution.completed`, `exposure.calculated`, `proposal.created`, `policy.decided`, `approval.recorded`, `action.requested`, `action.unknown`, `action.reconciled`, `verification.completed`, `case.escalated`, `case.terminal`.
