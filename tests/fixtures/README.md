# Fixture conventions

Fixtures are deterministic, versioned, tenant-scoped inputs for contract, integration,
replay, and acceptance tests. Every fixture must declare its schema/version, seed, mode
(`live` or `replay`), provenance, and expected terminal outcome where applicable.

Fixtures must not contain credentials, real payment secrets, unnecessary PII, or sealed
held-out evaluation inputs. Simulator output must remain explicitly labeled as replay or
test data and must never be presented as live production evidence.
