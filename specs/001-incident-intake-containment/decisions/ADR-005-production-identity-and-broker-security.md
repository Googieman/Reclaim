# ADR-005: Production identity and broker security overlay

- Status: Accepted for implementation
- Date: 2026-09-04

## Context

The local REPLAY/T153 profile intentionally uses development-only HTTP,
plaintext broker transport, and fixture identities. Those defaults must remain
usable for deterministic validation, but they are not sufficient for a
production deployment. The production path also needs explicit credential
rotation semantics for the n8n-managed HTTP and Kafka references.

## Decision

Keep local and production security profiles separate. The production Compose
overlay requires HTTPS OIDC JWKS discovery, HTTPS Vault, Keycloak HTTPS, Vault
TLS 1.3, n8n secure cookies/encryption, and Redpanda SASL_SSL with mandatory
client certificates. Redpanda authorization defaults to deny and its
certificate/SASL principal must match an explicit topic-operation allowlist in
`infra/redpanda/production-security.yaml` and `production-acl.yaml`.

n8n credential rotation is explicit and staged. A new non-secret revision creates
versioned credentials, rewires the managed workflows, verifies all references,
and only then permits activation. Previous credentials are never deleted by the
bootstrap script; operators revoke them after a successful smoke test and audit.

## Consequences

- T153 and REPLAY continue to use their existing plaintext and fixture defaults;
  this is not production qualification.
- Production startup fails when identity, TLS, SASL, or credential inputs are
  absent rather than silently falling back to development values.
- Broker ACL application and certificate issuance remain deployment operations;
  the checked-in policy contains principals and permissions but no secrets.
- PostgreSQL remains authoritative for business state and the application
  outbox/inbox reconciliation remains mandatory even after broker authentication.

## Alternatives considered

- Replacing all local defaults with TLS/SASL: rejected because it would break
  deterministic local/T153 validation and require credentials in test fixtures.
- Treating a broker offset or authenticated envelope as business authority:
  rejected because transport identity cannot replace PostgreSQL outbox
  reconciliation.
- Updating a credential in place or deleting the old credential automatically:
  rejected because n8n's public API does not provide a safe universal read/update
  contract and an interrupted rotation could strand the active workflow.
