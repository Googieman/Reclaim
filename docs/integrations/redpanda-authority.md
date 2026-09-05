# Redpanda event authority boundary

Redpanda is transport only. A consumer accepts a domain message only when all of
the following checks pass:

- the authenticated caller is an allowlisted non-human service identity with the
  `service` role and the event tenant matches that context;
- the envelope producer is one of the explicitly allowlisted US1 event writers;
- the schema version is supported and the envelope checksum matches its canonical
  payload; and
- the same tenant and `event_id` exist in PostgreSQL `outbox_events` with matching
  event type, aggregate identity, schema version, producer, correlation/causation
  identity, payload, and payload checksum.

The PostgreSQL reconciliation occurs before the inbox-handled transition or any
Neo4j write. Missing outbox rows, identity/checksum mismatches, unauthorized
producers, and database failures fail closed. A Redpanda offset, acknowledgement,
or envelope checksum is not business authority.

## Identity configuration

The current adapter enforces an application-level allowlist for the authenticated
OIDC service subject and for the event producer field. The temporary local
validation setup uses `reclaim-event-relay` with plaintext transport. The
production overlay supplies broker-native SASL_SSL, mandatory client
certificates, default-deny authorization, and the explicit principal/topic
allowlist from `infra/redpanda/production-security.yaml` and
`production-acl.yaml`. Deployment operators must still verify certificate
issuance, ACL application, and principal binding before activation; no live
broker qualification is claimed by static configuration tests. PostgreSQL
outbox reconciliation remains mandatory in production.
