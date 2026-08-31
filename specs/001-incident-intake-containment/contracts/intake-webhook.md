# Intake and Razorpay Webhook Contract

## Contract versions and authority

- The incident-intake contract remains `1.0.0`.
- The accepted Razorpay webhook request/processing contract is `2.0.0`. This is a
  breaking contract change from the earlier case-optional semantics because an
  authenticated webhook may no longer be accepted without authoritative association.
- `VerifiedProviderCorrelation` is a nested, provider-specific schema at version
  `1.0.0`. It is intentionally not a universal merchant-correlation framework.
- The shared contract `schema_version` is metadata for the declared contract. It does
  not make a caller-supplied `tenant_id`, `case_id`, `incident_id`, `merchant_id`, or
  transport `correlation_id` authoritative.

## Incident intake command

Required fields: `schema_version`, `tenant_id`, `source`, `received_at`, `correlation_id`,
reporter context, and untrusted report content/reference.

Response states: accepted with `incident_id`/`case_id`, duplicate acknowledged with
existing identity, rejected, or quarantined with reason and audit reference.

The intake boundary validates authentication, tenant membership, payload size/schema,
and idempotency before creating business state. Customer/report content is untrusted
and cannot provide policy, tool, or provider-association instructions. The incident
`correlation_key` is an incident-level deduplication/reference value; it is not a
provider-to-case authority and cannot create a provider mapping by itself.

## VerifiedProviderCorrelation v1.0.0

After original-payload authenticity succeeds, the configured provider connector MUST
derive and retain this object from the verified provider payload and configured
connector scope:

| Field | Requirement | Authority rule |
|---|---|---|
| `correlation_schema_version` | Required; `1.0.0` | Identifies this object schema. |
| `provider` | Required; `razorpay` for this contract | Derived from the configured connector, never trusted from a caller. |
| `connector_id` | Required | The configured provider connection identity, not a caller-selected connector. |
| `provider_event_id` | Required | Provider event identity extracted from the provider payload/header and checked against the signed payload when present. |
| `provider_payment_id` | Required for supported `payment.*` events | Extracted from the signed payment entity; this is the minimum FS-001 payment correlation identifier. |
| `provider_order_id` | Optional when present | Extracted from the signed payment/order entity and checked against the same mapping when present. |
| `merchant_reference` | Optional when present | Extracted only from the signed provider payload and used only as a secondary mapping consistency key. It is never accepted from the caller and is not sufficient by itself for an FS-001 payment mapping. |
| `verification` | Required | Contains `state=verified`, verification method/provenance, original payload checksum, verifier version, and verification timestamp. |

For a supported event family without a payment identifier, a provider order identifier
or a pre-registered provider-event mapping is required. If the provider payload does
not expose a supported stable resource identifier, the event is unresolved and cannot
be accepted into a case. When multiple provider identifiers are present, they MUST
resolve to the same mapping; disagreement is a correlation conflict.

The verified object is derived only after signature, checksum, configured connector,
event identity, event type, and timestamp checks pass. A body field, header, merchant
reference, or tenant value that is not covered by the configured verification and
connector rules is untrusted evidence and cannot be promoted into this object.

## Razorpay Test Mode webhook request

The request retains the original bytes, checksum, signature, provider event metadata,
and common tenant/correlation context. It MUST also produce the verified correlation
object above before an accepted outcome is possible. The processing result and durable
webhook delivery retain the object and the authoritative mapping reference.

An accepted or duplicate processing response MUST include `authoritative_mapping_id`
and the mapping-derived `incident_id`/`case_id`. A rejected/quarantined response
includes the association status/reason and audit reference but does not return a
guessed or caller-selected case association.

Caller-supplied `case_id` and `incident_id` are optional assertion fields on the
processing command, not ownership fields. Caller-supplied `tenant_id`/`merchant_id`
and the transport `correlation_id` are likewise context or audit values only. No caller
field can create, select, or mutate a provider-correlation mapping.

## Required processing order

1. Preserve original request bytes and checksum.
2. Apply the configured provider authenticity verification mechanism using the
   tenant-scoped secret reference.
3. Require provider event identifier and event timestamp/type fields needed by the
   connector schema.
4. Derive `VerifiedProviderCorrelation` v1.0.0 from the verified provider payload and
   configured connector identity.
5. Resolve the verified correlation against exactly one active PostgreSQL
   `ProviderCorrelationMapping` using provider/connector scope and the provider event,
   payment, order, and any signed merchant reference present. The lookup MUST NOT use
   caller-supplied tenant, merchant, case, incident, or transport correlation values as
   authority.
6. Require the mapping's authoritative tenant, incident, case, and related order/
   payment context to be internally consistent. An absent, ambiguous, revoked, or
   cross-tenant mapping is unresolved and cannot be accepted.
7. If caller-supplied `case_id` or `incident_id` is present, compare it with the
   mapping. A mismatch is rejected/quarantined; absence does not prevent resolution.
8. Associate only with the tenant and case returned by the mapping, persist the
   verified correlation and mapping reference, and enforce delivery idempotency.
9. Quarantine invalid, incomplete, unresolved, conflicting, or mismatched events with
   an audit record; never create a mapping or guess a case from the webhook.
10. Acknowledge a valid duplicate without replaying downstream business processing.

## PostgreSQL mapping lookup semantics

The minimum `ProviderCorrelationMapping` record contains:

| Field | Requirement |
|---|---|
| `mapping_id` | Stable mapping identity. |
| `correlation_schema_version` | `1.0.0`, matching the verified correlation schema. |
| `provider`, `connector_id` | Provider and configured provider-connection scope. |
| `provider_event_id` | Optional event-specific identity; retained when pre-registered. |
| `provider_payment_id`, `provider_order_id` | Optional individually, but at least one provider-native resource identity is required; payment mappings for `payment.*` require the payment ID. |
| `merchant_reference` | Optional signed/provider-derived secondary key. |
| `tenant_id`, `incident_id`, `case_id` | Required authoritative owner, with tenant-consistent composite relationships. |
| `related_order_reference`, `related_payment_reference` | Optional opaque references to trusted merchant order/payment context. |
| `mapping_source`, `mapping_source_reference`, `mapping_source_checksum` | Required provenance for trusted merchant-side context or server-side pre-registration. |
| `mapping_status`, `created_at`, `verified_at`, `revoked_at` | Lifecycle and provenance timestamps; only one active mapping may resolve the identity. |

The authoritative mapping is resolved by the verified identifiers, not by a caller's
case selection. For FS-001 payment events, the provider payment identifier is the
primary resource lookup key; provider order ID and signed merchant reference narrow or
confirm the same candidate when present. A provider-event-specific mapping may be
used when the event ID was pre-registered. All supplied identifiers must intersect to
one active mapping. Zero candidates, multiple candidates, or candidates that disagree
on tenant/case/incident are `unresolved_association` and are quarantined.

The mapping's tenant is returned by PostgreSQL and must equal the tenant of the
configured connector/authentication scope. A mapping found for a different tenant is
a cross-tenant association failure, not a valid alternative. Accepted rows store the
mapping reference and authoritative `incident_id`/`case_id`; they do not store caller
IDs as the source of those values.

## Idempotency and outcomes

- Valid delivery idempotency remains separate from Action Gateway idempotency and is
  keyed by `(tenant_id, connector_id, provider_event_id)` for the configured connector
  scope.
- A duplicate with the same verified correlation and original payload returns the
  existing authoritative mapping/case outcome and performs no downstream processing.
- Reuse of a provider event ID with different bytes or a conflicting verified
  correlation is a fail-closed identity/correlation conflict; it is quarantined and
  never reattached to another case.
- An authenticated event with no authoritative mapping is retained as an auditable
  `unresolved_association` quarantine with no incident/case attachment and no mapping
  creation. It may be reviewed or explicitly replayed after a trusted mapping is
  provisioned, subject to the same v2.0.0 contract.

## Compatibility and migration

The authority change is a hard cutover for accepted webhook processing. There is no
temporary compatibility mode that accepts a caller-selected case, even when the case
is in the same tenant. Existing case-only callers must migrate to v2.0.0 and may keep
their IDs only as optional assertions after the trusted mapping is provisioned.

Existing persisted development deliveries require a one-time migration/backfill from
trusted merchant order/payment context. A row may be promoted or retained as accepted
only when that context produces exactly one mapping; rows without proof remain
unresolved/quarantined and are never backfilled from their stored caller-supplied
`case_id` or `incident_id`. Existing replay/simulator fixtures must add the v1.0.0
correlation object inputs and authoritative mapping fixture/reference. The current
`razorpay-test-v1` valid fixture therefore needs a v2.0.0 replacement with provider
payment/order correlation and a recomputed signature before it can exercise acceptance.

The exact provider header, signature encoding, secret rotation, and Test Mode fixture
values remain connector implementation validation items. The trust, correlation,
mapping, assertion, quarantine, and idempotency rules above are fixed.
