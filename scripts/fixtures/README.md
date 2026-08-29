# Fixture loading conventions

Fixture loaders must validate schema version, tenant scope, checksum, replay/live label,
and declared provenance before use. Loaders are read-only and must reject credentials,
unsealed held-out data, generic executable instructions, and cross-tenant references.
