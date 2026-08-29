# FS-001 shared contract package

`packages/contracts/` is the source of truth for language-level boundary schemas.
The feature-local Markdown contracts remain the normative, language-neutral behavior
specification; these Pydantic models encode that specification without implementing
services or side effects.

## Ownership and versioning

- Contract definitions are owned here and are consumed by APIs, workers, adapters,
  simulators, and tests through the same model shapes.
- Every request, event, decision, tool call, and audit record carries a schema version,
  `tenant_id`, and `correlation_id`. Event and gateway contracts add their required
  causation and identity fields.
- `schema_registry.py` defines the supported contract major version and compatibility
  rules. A compatible version may not widen an allowlist or remove a required safety
  field.
- Generated language bindings, if added later, must be derived from these contracts and
  must retain the same version and ownership metadata. Hand-edited generated output is
  not authoritative.
- Contract changes that affect ownership, safety, authority, or compatibility require
  an explicit architecture decision before implementation.

The models are deliberately side-effect-free. PostgreSQL, Temporal, Redpanda, connector
credentials, and Action Gateway execution belong to later tasks and are not imported by
this package.
