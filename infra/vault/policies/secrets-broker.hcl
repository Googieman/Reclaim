# The broker may authenticate to Vault only for these exact canonical deployment
# paths. A per-environment deployment renders this file for its tenant; no
# wildcard/listing/write capability is granted to the broker.
path "secret/data/reclaim/final/model/provider" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/model/serving" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/n8n/database" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/n8n/queue" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/n8n/encryption" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/n8n/bootstrap" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/telemetry/export" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/telemetry/langfuse" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/mlflow/publisher" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/training/huggingface" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/mlflow/database" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/mlflow/artifacts" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/broker/audit-database" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/api/database" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/api/evidence" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/gateway/database" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/relay/database" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/projection/database" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/projection/neo4j" {
  capabilities = ["read"]
}
path "secret/data/tenants/tenant-canonical-demo/connectors/razorpay-test-actions/webhook" {
  capabilities = ["read"]
}
path "secret/data/tenants/tenant-canonical-demo/connectors/razorpay-test-actions/action" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/n8n/service-client" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/kafka/producer" {
  capabilities = ["read"]
}
path "secret/data/reclaim/final/tenants/tenant-canonical-demo/kafka/n8n-consumer" {
  capabilities = ["read"]
}
