# Intake and Razorpay Webhook Contract

## Incident intake command

Required fields: `schema_version`, `tenant_id`, `source`, `received_at`, `correlation_id`, reporter context, and untrusted report content/reference.

Response states: accepted with `incident_id`/`case_id`, duplicate acknowledged with existing identity, rejected, or quarantined with reason and audit reference.

The intake boundary validates authentication, tenant membership, payload size/schema, and idempotency before creating business state. Customer/report content is untrusted and cannot provide policy or tool instructions.

## Razorpay Test Mode webhook

Required processing order:

1. Preserve original request bytes and checksum.
2. Apply the configured provider authenticity verification mechanism using the tenant-scoped secret reference.
3. Require provider event identifier and event timestamp/type fields needed by the connector schema.
4. Associate only with the configured tenant/connector.
5. Enforce uniqueness on `(tenant_id, connector_id, provider_event_id)`.
6. Quarantine invalid, incomplete, or mismatched events; do not let them influence case processing.
7. Acknowledge a valid duplicate without replaying downstream business processing.

The exact provider header, signature encoding, secret rotation, and Test Mode fixture values are connector implementation validation items and must be confirmed before coding; the trust and idempotency contract above is fixed.
