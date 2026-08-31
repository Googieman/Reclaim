# Razorpay Test Mode fixtures

These checked-in fixtures are deterministic replay inputs only. They contain no
provider secret and are never evidence that a live Razorpay integration was
validated. Tests derive a signature with an in-memory test secret when they need
to exercise the verifier.

Every fixture must retain `mode: replay`, a fixture version, tenant/connector
identity, provider event identity, event metadata, original payload, and a
failure variant label where applicable. Accepted v2 fixtures additionally carry
provider payment/order correlation and a `trusted_mapping` seed sourced from
merchant-side context. Secret rotation is represented by references in
configuration, never by fixture values.
