# The model gateway receives redacted inputs and has no action credential path.
path "secret/data/tenants/+/connectors/+/evidence" {
  capabilities = ["read"]
}
