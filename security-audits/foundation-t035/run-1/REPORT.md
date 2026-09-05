# RECLAIM Foundation Security Audit — T001–T035

Run: `foundation-t035/run-1`
Date: 2026-08-30
Mode: read-only; no production, specification, ADR, task, or status files were modified.

## Executive result

No currently exploitable CRITICAL, HIGH, or MEDIUM vulnerability was confirmed in the T001–T035 scope.

One real latent authorization defect was independently reproduced: OIDC roles are flattened across tenants, so a principal who belongs to tenants A and B and carries the global `approver` role is accepted as an approver in tenant B. The independent validator confirmed the behavior and the no-write harness reproduced it. It is not counted as a current confirmed vulnerability because T001–T035 contains no reachable API, approval consumer, Action Gateway, connector, model gateway, or production event handler that can turn that incorrect decision into a privilege-bearing action. It is a hard gate for T036.

The audit did not attempt to fix any finding. The local test run used for this audit was `59 passed, 11 skipped`; the skipped tests require live service environment variables. `PROJECT_STATUS.md` records a previous live-service result of 70 passed tests, but those services were not available for independent rerun here. At audit start, the worktree was already not clean because the installed audit skill files were untracked; audit artifacts are intentionally added under this run directory.

## Requested finding classification

### Confirmed CRITICAL

None.

### Confirmed HIGH

None.

### Confirmed MEDIUM

None.

### Rejected as current T001–T035 exploits / false-positive candidates

These items were investigated. Several describe real weaknesses or incomplete future controls, but none met the skill’s requirement for a current reachable attack with meaningful impact in the completed foundation:

- OIDC tenant-role binding: behavior is real, but no current request path consumes the decision. Treat as a T036 blocker, not a false statement.
- Raw `PostgresUnitOfWork.connection` exposure and caller-supplied tenant context: a future tenant-reachable handler could mutate the transaction setting or use raw SQL, but no such handler exists in scope.
- Approval signal spoofing and arbitrary Temporal stage/activity names: the workflow has the permissive behavior, but no current production activity or side-effecting consumer is registered.
- Activity-result trust, optional approval fields in the Action Gateway contract, and unknown model tool names: these are contract/workflow gaps without a model gateway, Action Gateway, or connector sink in T001–T035.
- Self-declared Redpanda tenant, producer, and payload checksum: deserialization and dispatch trust the envelope, but there is no production event handler or exposed broker path in scope.
- MinIO check-then-put race and Redis lock release without compare-and-delete: the implementation weaknesses exist, but no current business operation relies on them for an exploitable financial or action decision.
- Global policy-row mutability and single-column policy references: future policy-owner/integrity risks; no current policy service or consumer provides an attacker path or consequential authorization decision.
- Vault wildcard policy, development defaults, unauthenticated observability defaults, and missing deployment ACLs/TLS: deployment-dependent hardening issues; no production deployment configuration or external ingress exists in the audited tree.
- Injection, unsafe deserialization, SSRF, path traversal, shell execution, leaked production secrets, and arbitrary network access: no reachable sink was found. SQL is parameterized, JSON is contract-validated, and evidence object names reject traversal-like segments.

The complete machine-readable disposition is in `findings.json`.

## Strongest controls already present

- PostgreSQL RLS is enabled and forced on the business/event/audit tables. Tenant-scoped policies require the transaction-local tenant context; the repository/UoW path uses transaction-local configuration.
- PostgreSQL is treated as authoritative, while Temporal is orchestration, Redpanda is at-least-once transport, Neo4j is rebuildable, and Redis is explicitly non-authoritative.
- Outbox/inbox identities are tenant-scoped and duplicate/conflicting checksum reuse is rejected.
- Audit records carry a checksum chain and database triggers block audit UPDATE/DELETE.
- OIDC verification requires configured issuer/audience, signature validation, allowlisted algorithms, and required `exp`, `iat`, `iss`, and `sub` claims before tenant membership is checked.
- Parameterized SQL, Pydantic extra-field rejection in shared contracts, bounded Redis naming/TTL behavior, safe MinIO tenant path segments, and MinIO checksum verification reduce common injection and substitution paths.
- Connector manifests restrict capabilities and evidence operations; defaults keep replay mode and live financial actions disabled.
- The model contract is proposal-oriented and rejects a small set of direct side-effect tool names; this is useful containment but is not a substitute for a positive capability policy at the future model gateway.

## Most dangerous architectural areas

1. Tenant authorization composition: flat OIDC roles, caller-supplied UoW tenant IDs, and public raw connections must not be allowed to decide authorization independently.
2. The Temporal-to-action boundary: approval signals, dynamic stages, and activity results need authenticated, authoritative records and an allowlisted state machine before any action activity exists.
3. The event trust boundary: producer identity, tenant binding, payload checksum recomputation, broker ACLs, and inbox handling must be established before production handlers are connected.
4. Deterministic action enforcement: the future Action Gateway must require a valid approval/policy decision, bind it to tenant/case/proposal/connector/operation, and reject ambiguous or optional authorization fields.
5. Persistence integrity: policy ownership/immutability, composite tenant references, MinIO write atomicity/versioning, and Redis token-safe release need hardening before those helpers carry financial or action state.

## T036 gate decision

**Block T036.** Do not begin the next implementation slice until the tenant-role model is made tenant-specific or otherwise authoritative, the principal-to-UoW binding is enforced, and negative authorization tests demonstrate that a role valid in tenant A cannot authorize tenant B. The Temporal approval and Action Gateway boundary candidates should be closed in the same gate because they are the first likely consumers of this authorization decision.

## Recommended remediation order (no remediation was performed)

1. Define signed/authoritative `(tenant, subject, role)` authorization, bind authenticated principals to UoW tenant context, remove or tightly gate raw connection access, and add cross-tenant negative tests.
2. Specify a fixed Temporal state machine and validate approval identity, role, policy version, status, expiry, tenant, case, and proposal before waking action-capable stages.
3. Make the Action Gateway a mandatory deterministic validator: positive tool/operation allowlists, required approval where policy requires it, exact tenant/case/proposal/connector binding, idempotency, and verification.
4. Authenticate event producers, enforce broker ACLs, recompute payload checksums, validate tenant/aggregate ownership, and keep inbox deduplication authoritative in PostgreSQL.
5. Add database-level policy integrity/immutability and composite tenant references; restrict service roles and Vault paths to least privilege.
6. Harden MinIO with conditional/versioned or object-locked writes and fix Redis release with compare-and-delete; then validate deployment TLS, network exposure, observability auth, and secret defaults.
7. Re-run the full live-service negative test matrix and record actual results and provenance before unblocking the next milestone.

## Validation limitations

Docker and the live service environment were unavailable in this audit shell, so PostgreSQL/Temporal/Redpanda/Neo4j/MinIO/Redis/Keycloak/Vault integration claims were not independently rerun. The audit therefore distinguishes source-confirmed behavior from deployment- or future-service-dependent exploitability and does not present skipped tests as passing.
