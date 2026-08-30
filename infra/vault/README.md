# Vault boundary

Secret values are never committed. The Action Gateway identity is the only
service allowed to read `secret/data/tenants/<tenant>/connectors/<connector>/action`.
Workflow, model, API, and UI identities use separate Vault policies and cannot
read that path. Secret rotation replaces the versioned KV value and refreshes the
short-lived service authentication; callers retain only the path reference.
