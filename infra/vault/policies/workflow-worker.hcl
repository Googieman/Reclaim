# Workflow orchestration does not receive merchant side-effect credentials.
path "secret/data/tenants/+/workflow" {
  capabilities = ["read"]
}
