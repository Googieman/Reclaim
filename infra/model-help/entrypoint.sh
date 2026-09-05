#!/bin/sh
set -eu

: "${MODEL_PATH:?MODEL_PATH is required}"
: "${MODEL_API_KEY:?MODEL_API_KEY is required}"

exec llama-server \
  -m "$MODEL_PATH" \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --api-key "$MODEL_API_KEY" \
  --no-webui \
  --no-agent \
  --parallel 1 \
  --ctx-size 4096 \
  --n-predict 1024
