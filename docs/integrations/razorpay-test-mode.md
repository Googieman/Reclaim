# Razorpay Test Mode webhook connector

The FS-001 connector accepts only Razorpay Test Mode webhook declarations. The
adapter verifies the exact original request bytes with tenant-scoped HMAC-SHA256
material, checks the configured signature and provider-event headers, requires
provider event identity/type/timestamp metadata, and retains the raw payload
checksum for the processing boundary.

The configured verification reference is:

`secret/data/tenants/<tenant>/connectors/razorpay-test/webhook`

The intake API may read only this verification path. It cannot read Action
Gateway credentials. Secret rotation is a validation seam for current/previous
versioned references; secret values are provisioned out of band.

## D3 contract migration

The approved webhook association contract is v2.0.0. After signature verification,
the connector must derive `VerifiedProviderCorrelation` v1.0.0 from the signed payload:
`provider_event_id` plus `provider_payment_id` is required for supported `payment.*`
events; `provider_order_id` and a signed merchant reference are retained when present.
The intake path resolves those identifiers through a pre-provisioned PostgreSQL
provider-correlation mapping. `case_id`, `incident_id`, `tenant_id`, and merchant IDs
from callers remain assertions/context only.

Existing case-only callers and the current `razorpay-test-v1` valid fixture are not
compatible with an accepted v2.0.0 delivery by themselves. Migration `005` provisions
the authoritative mapping table, quarantines legacy accepted rows without proof, and
adds the verified correlation fields to delivery/quarantine records. Valid replay
fixtures provision a trusted mapping before processing; their test signature is
recomputed over the changed original payload by the fixture loader. Invalid or
incomplete fixtures remain useful for quarantine coverage.

The files under `tests/fixtures/razorpay/` are labeled `replay` and contain no
secret. They validate deterministic adapter behavior only. No live Razorpay
provider behavior is claimed until an explicitly configured Test Mode run passes
configuration, connectivity, authenticity, and audit validation.
