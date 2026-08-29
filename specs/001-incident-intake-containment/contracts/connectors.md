# Evidence and Action Connector Contract

Each connector manifest declares:

- `connector_id`, `tenant_id`, contract version, live/simulator mode;
- allowed resource types and operations;
- authentication and secret-scope reference;
- request schema, response schema, pagination/limits, timestamp semantics;
- idempotency and duplicate behavior;
- failure states: unavailable, partial, stale, invalid, timeout, unknown result;
- audit and evidence provenance requirements.

## Evidence operations

Evidence connectors are read-only and support the approved resources: sessions, devices, profile changes, orders, fulfillment, and payments. A response includes source identity, observed time, collection time, completeness, raw artifact reference/checksum, normalized facts, and connector status.

## Action operations

Action connectors expose only allowlisted merchant-controlled operations. The Action Gateway, not the model or workflow, supplies credentials. Each action returns `accepted`, `rejected`, `completed`, `failed`, or `unknown`; unknown requires reconciliation contract before retry.

## Simulator requirements

The deterministic simulator must implement the same request/response schemas and allowlist. Fixtures must support valid, invalid, partial, stale, duplicate, out-of-order, timeout, and unknown-result outcomes with deterministic seeds and timestamps. Simulator output is labeled and cannot be represented as live production evidence.
