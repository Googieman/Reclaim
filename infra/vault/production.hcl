ui = false
disable_mlock = true
api_addr = "https://vault:8200"
cluster_addr = "https://vault:8201"

listener "tcp" {
  address            = "0.0.0.0:8200"
  cluster_address    = "0.0.0.0:8201"
  tls_disable       = "false"
  tls_cert_file     = "/run/secrets/vault-tls-cert"
  tls_key_file      = "/run/secrets/vault-tls-key"
  tls_min_version   = "tls13"
}

storage "file" {
  path = "/vault/file"
}

# Initialization, unseal, auth roles, and policies are performed out of band
# by the deployment secret manager. No root token or secret value belongs here.
