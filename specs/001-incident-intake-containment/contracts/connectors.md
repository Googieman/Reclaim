# Evidence and Action Connector Contract

Each connector manifest declares:

- `connector_id`, `tenant_id`, contract version, live/simulator mode;
- allowed resource types and operations;
- authentication and secret-scope reference;
- request schema, response schema, pagination/limits, timestamp semantics;
- idempotency and duplicate behavior;
- failure states: unavailable, partial, stale, invalid, timeout, unknown result;
- audit and evidence provenance requirements.

## Webhook-capable connector identity

A webhook-capable connector MUST declare the versioned provider-correlation schema it
derives after authenticity verification, including the provider event identifier and
the provider-native resource identifiers used for ownership lookup. It MUST record
verification state/provenance and the original payload checksum. Caller-supplied
tenant, merchant, incident, or case values are not provider identity and cannot be
used to create or select an authoritative mapping.

For the Razorpay Test Mode v2.0.0 webhook contract, `provider_event_id` plus
`provider_payment_id` is the minimum accepted correlation for `payment.*` events.
`provider_order_id` and a signed merchant reference are optional additional
consistency identifiers when present. A connector must report an unresolved
correlation when the supported provider payload does not expose the required stable
resource identifier.

## Evidence operations

Evidence connectors are read-only and support the approved resources: sessions, devices, profile changes, orders, fulfillment, and payments. A response includes source identity, observed time, collection time, completeness, raw artifact reference/checksum, normalized facts, and connector status.

## Action operations

Action connectors expose only allowlisted merchant-controlled operations. The Action Gateway, not the model or workflow, supplies credentials. Each action returns `accepted`, `rejected`, `completed`, `failed`, or `unknown`; unknown requires reconciliation contract before retry.

## Simulator requirements

The deterministic simulator must implement the same request/response schemas, provider
correlation derivation, mapping lookup semantics, and allowlist as the live connector.
Fixtures must support valid, invalid, partial, stale, duplicate, out-of-order, timeout,
unknown-result, missing-mapping, mapping-conflict, assertion-mismatch, and
cross-tenant-association outcomes with deterministic seeds and timestamps. Simulator
output is labeled and cannot be represented as live production evidence.
