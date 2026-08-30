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

The files under `tests/fixtures/razorpay/` are labeled `replay` and contain no
secret. They validate deterministic adapter behavior only. No live Razorpay
provider behavior is claimed until an explicitly configured Test Mode run passes
configuration, connectivity, authenticity, and audit validation.
