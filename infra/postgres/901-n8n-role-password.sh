#!/usr/bin/env bash
set -Eeuo pipefail

: "${N8N_DB_PASSWORD:=reclaim-n8n-development}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set ON_ERROR_STOP=1 \
  --set n8n_password="$N8N_DB_PASSWORD" <<'SQL'
ALTER ROLE n8n LOGIN PASSWORD :'n8n_password';
SQL
