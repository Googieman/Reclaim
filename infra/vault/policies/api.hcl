# API identity receives only non-side-effect configuration references.
path "secret/data/tenants/+/api" {
  capabilities = ["read"]
}
