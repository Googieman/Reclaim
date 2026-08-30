# API identity receives only non-side-effect configuration references.
path "secret/data/tenants/+/api" {
  capabilities = ["read"]
}

# Inbound signature verification has no merchant mutation authority.
path "secret/data/tenants/+/connectors/+/webhook" {
  capabilities = ["read"]
}
