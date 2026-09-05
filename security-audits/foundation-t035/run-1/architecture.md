# RECLAIM Foundation T001–T035 Security Audit Architecture

## Scope and audit posture

Target: `C:\Users\varug\Reclaim`, limited to T001–T035 foundation code, packages, `infra/` configuration, security/integration tests, and the requested governance/specification references. The user requested no fixes and no work beyond T035.

The task ledger and project status mark T001–T035 complete. The repository contains the foundation contracts and adapters, but no connected `backend/api/`, `backend/connectors/`, `backend/model-gateway/`, `backend/action-gateway/`, or `backend/workflows/activities/` implementation. Therefore, a finding is confirmed only where the foundation code itself crosses a trust boundary or where a concrete foundation entry point can be driven; future-service risks are separately identified as blocking risks or hardening notes when no current sink exists.

No prior foundation security-audit `findings.json` run was found. `security-audits/trivy/` exists but is not a prior run in the skill’s output format. Additional audit runs may find different paths.

## Application and deployment model

RECLAIM is a tenant-ready, multi-service incident-response platform for merchant-controlled account-compromise intake, evidence collection, deterministic attribution/exposure, bounded analysis, policy/approval, Action Gateway execution, verification, and escalation. The planned stack is Python 3.12/FastAPI services and Temporal workers, a Next.js UI, Pydantic contracts, PostgreSQL, Redpanda, Neo4j, MinIO, Redis, Keycloak/OIDC, Vault, and redacted observability/model metadata sinks. The authoritative deployment plan is Docker Compose, but no Compose file is present in the scoped tree and Docker/runtime services were not available in this audit environment.

Primary actors are merchant/operator users, reviewers, approvers, escalation owners, policy owners, service identities, approved merchant connectors, the workflow worker, the model gateway, the Action Gateway, and event/projection consumers. Customer text, webhook fields, evidence, and model output are untrusted. The model is intended to read redacted case/evidence data and produce typed proposals only.

## Authority and trust boundaries

* PostgreSQL owns business state, policy, approvals, actions, verification, escalation, audit, replay/evaluation metadata, and outbox/inbox state.
* Temporal owns orchestration history, retries, timers, and signals; activities are expected to re-read authoritative state.
* Redpanda is at-least-once transport; the PostgreSQL outbox/inbox is the delivery boundary.
* Neo4j is a rebuildable relationship projection and must not be authoritative.
* MinIO stores tenant-prefixed raw evidence/artifacts with content checksums; normalized facts remain in PostgreSQL.
* Redis is bounded cache/lock/rate-limit/coordination only.
* Keycloak/OIDC supplies signed identity, tenant claims, and roles. Vault supplies scoped secrets; action connector secrets are intended for the Action Gateway only.
* The model capability enum is read/proposal-only. The Action Gateway is intended to be the sole merchant-system side-effect boundary.

Key enforcement paths:

* Shared Pydantic contracts require nonblank tenant/correlation context and reject extra fields (`packages/contracts/common.py`).
* `PostgresUnitOfWork` starts a transaction, applies transaction-local `reclaim.tenant_id`, and constructs tenant-scoped repositories (`backend/app/db/unit_of_work.py`, `backend/app/db/tenant_context.py`).
* Migration `002_tenant_isolation.sql` enables and forces RLS on all business/event/audit/webhook tables. Normal policies require the tenant setting; global policy rows are readable across tenants by design.
* OIDC verification uses configured issuer/audience, an allowlisted algorithm tuple, signature verification, expiry/issued-at/issuer/subject requirements, and tenant membership (`backend/app/auth/oidc.py`).
* Connector manifests reject wildcards and limit evidence operations to `read` (`backend/app/contracts/registry.py`).
* Outbox/inbox identities are tenant-scoped and checksum-conflicting reuses are rejected. Audit records are checksum-linked in `AuditChain`; PostgreSQL blocks audit UPDATE/DELETE.
* MinIO keys reject traversal-like path segments and verify stored checksums. Neo4j rebuild rejects mixed-tenant input. Redis names are tenant-prefixed and TTL-bounded.

## Input surfaces and dangerous sinks

Current executable foundation surfaces are Python APIs/adapters rather than HTTP routes:

* Pydantic contract construction accepts caller-supplied tenant IDs, references, payloads, action/proposal fields, policy/approval fields, event producer/checksum fields, model tool names, and workflow stages/signals.
* PostgreSQL repositories accept structured values and issue parameterized SQL. The UoW exposes its raw connection as a public attribute.
* Redpanda deserialization accepts broker bytes, parses JSON, and dispatches using the envelope’s self-declared tenant ID and producer.
* Temporal workflow start commands, arbitrary stage names, signals, recovery commands, and activity results cross the orchestration boundary.
* MinIO object names/content and metadata cross the object-storage boundary; Neo4j projection queries write tenant/event properties; Redis names/values cross a coordination boundary.
* OIDC token strings and configured signing/JWKS inputs cross the authentication boundary; Vault paths and service identity are constructor inputs.
* Telemetry/model data is recursively redacted by key-name heuristics, then sent to configured sinks.

No shell/eval/dynamic import, direct HTTP fetch, archive extraction, HTML rendering, or application endpoint is present in the T001–T035 scope. `PyJWKClient`, MinIO, Neo4j, Redis, Vault, and broker clients are only instantiated through adapters and depend on deployment configuration.

## Comparable baseline

The closest comparables are SOAR playbook platforms and payment-risk controls. They commonly allow read-only automation, require asset-level/manual approval for high-impact writes, and use durable execution/idempotency for integrations. RECLAIM’s intended differentiator is narrower model authority: typed advisory output, deterministic policy/approval, and an isolated gateway. This baseline makes unverified approval, tenant, or connector claims materially security-relevant rather than ordinary automation behavior.

## Validation constraints

The local no-bytecode/no-cache test run passed 59 tests and skipped 11 opt-in live-service tests because the required environment variables were absent. `PROJECT_STATUS.md` records a previous 70-test run with temporary live PostgreSQL, Temporal, Redpanda, Neo4j, MinIO, Redis, Keycloak, and Vault services; this audit did not independently reproduce those live checks. The working tree was not clean at audit start: `.agents/skills/security-audit/` and `skills-lock.json` were untracked. Those files were preserved.
