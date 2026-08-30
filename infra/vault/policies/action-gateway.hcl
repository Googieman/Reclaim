# Action Gateway may read only tenant-scoped action connector secrets.
# Vault authentication and secret values are provisioned out of band.
path "secret/data/tenants/+/connectors/+/action" {
  capabilities = ["read"]
}

path "secret/metadata/tenants/+/connectors/+/action" {
  capabilities = ["read"]
}
