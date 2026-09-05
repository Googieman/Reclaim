# Vault boundary

Secret values are never committed. Production uses `production.hcl` with TLS
1.3 and file-backed storage; initialization, unseal, auth roles, and policies
are provisioned by the deployment secret manager. The Action Gateway identity is the only
service allowed to read `secret/data/tenants/<tenant>/connectors/<connector>/action`.
Workflow, model, and UI identities use separate Vault policies and cannot read
that path. The intake API may read only the matching
`secret/data/tenants/<tenant>/connectors/<connector>/webhook` verification path;
it cannot read action credentials. Secret rotation replaces the versioned KV value
and refreshes the short-lived service authentication; callers retain only the path
reference. Rotation is staged and audited: publish the replacement, validate
its consumer, then revoke the previous lease/version. Unknown or unavailable
secret reads fail closed before any connector invocation.
