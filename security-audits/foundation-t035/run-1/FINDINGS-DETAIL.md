# Finding details

## No confirmed exploitable findings

The independent validation pass confirmed no current CRITICAL, HIGH, or MEDIUM exploit in T001–T035. The completed foundation has adapters, contracts, workflows, and repository boundaries, but no connected API, connector, model gateway, Action Gateway, production workflow activity, or production event handler.

## Gate-blocking latent defect: OIDC roles are not tenant-bound

Evidence:

- `infra/keycloak/realm-reclaim.json:8-14` defines roles such as `approver` as global realm roles and `:64-79` maps tenant membership but no tenant-specific role assignment.
- `backend/app/auth/oidc.py:111-123` combines realm and resource roles into one flat set.
- `backend/app/auth/oidc.py:44-47` checks tenant membership and then checks only whether the role is present in that flat set.
- `backend/app/auth/oidc.py:100-103` applies that decision during verified-token processing.
- A no-write harness produced `authorized_in_tenant_b: True` for a principal with `tenant_ids=["tenant-a", "tenant-b"]` and global `approver` membership. The independent validator reproduced the same result while a tenant-scoped role registry declared the role only for tenant A.

This is a confirmed incorrect authorization decision in the foundation helper, but not a confirmed current privilege escalation: the only call sites are tests and there is no T001–T035 API or action sink. It should be remediated and negatively tested before T036 consumes the helper.

## Future-only candidates rejected by the current exploitability bar

The following were adversarially checked and retained as gate/hardening work rather than confirmed vulnerabilities: raw UoW tenant-context manipulation; same-case Temporal approval-signal spoofing; arbitrary workflow stages; unvalidated activity results; model tool and Action Gateway contract permissiveness; self-declared event tenant/producer/checksum; MinIO check-then-put races; token-unsafe Redis lock release; global policy DML and policy-reference tenant integrity; Vault wildcard scope; and development/observability deployment defaults.
