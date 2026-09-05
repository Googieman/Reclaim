#!/bin/sh
set -eu

: "${MODEL_API_KEY:?MODEL_API_KEY is required}"
: "${MODEL_MANIFEST_PATH:=/etc/reclaim/help-model-manifest.json}"
: "${MODEL_DIR:=/models}"

fail() {
  echo "reclaim-help-model: $1" >&2
  exit 1
}

manifest_string() {
  sed -n "s/^[[:space:]]*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" \
    "$MODEL_MANIFEST_PATH" | head -n 1
}

manifest_number() {
  sed -n "s/^[[:space:]]*\"$1\"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p" \
    "$MODEL_MANIFEST_PATH" | head -n 1
}

[ -r "$MODEL_MANIFEST_PATH" ] || fail "model manifest is unavailable"

manifest_status="$(manifest_string status)"
manifest_repository="$(manifest_string repository)"
manifest_revision="$(manifest_string revision)"
manifest_filename="$(manifest_string filename)"
manifest_sha256="$(manifest_string sha256)"
manifest_size_bytes="$(manifest_number size_bytes)"

[ "$manifest_status" != "disabled" ] || fail "model manifest is disabled"
[ -n "$manifest_repository" ] || fail "model repository is missing from manifest"
[ -n "$manifest_revision" ] || fail "model revision is missing from manifest"
[ -n "$manifest_filename" ] || fail "model filename is missing from manifest"
[ "$manifest_sha256" ] || fail "model checksum is missing from manifest"
[ "$manifest_size_bytes" ] || fail "model size is missing from manifest"

MODEL_REPOSITORY="${MODEL_REPOSITORY:-$manifest_repository}"
MODEL_REVISION="${MODEL_REVISION:-$manifest_revision}"
MODEL_FILENAME="${MODEL_FILENAME:-$manifest_filename}"
MODEL_SHA256="${MODEL_SHA256:-$manifest_sha256}"
MODEL_SIZE_BYTES="${MODEL_SIZE_BYTES:-$manifest_size_bytes}"

[ "$MODEL_REPOSITORY" = "$manifest_repository" ] || fail "model repository does not match manifest"
[ "$MODEL_REVISION" = "$manifest_revision" ] || fail "model revision does not match manifest"
[ "$MODEL_FILENAME" = "$manifest_filename" ] || fail "model filename does not match manifest"
[ "$MODEL_SHA256" = "$manifest_sha256" ] || fail "model checksum does not match manifest"
[ "$MODEL_SIZE_BYTES" = "$manifest_size_bytes" ] || fail "model size does not match manifest"

case "$MODEL_SHA256" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]* ) : ;;
  * ) fail "model checksum is not a lowercase SHA-256 digest" ;;
esac

expected_download_url="https://huggingface.co/$MODEL_REPOSITORY/resolve/$MODEL_REVISION/$MODEL_FILENAME?download=true"
MODEL_DOWNLOAD_URL="${MODEL_DOWNLOAD_URL:-$expected_download_url}"
[ "$MODEL_DOWNLOAD_URL" = "$expected_download_url" ] || fail "model download URL does not match manifest"

MODEL_PATH="${MODEL_PATH:-$MODEL_DIR/$MODEL_FILENAME}"
[ "$MODEL_PATH" = "$MODEL_DIR/$MODEL_FILENAME" ] || fail "model path must be inside the model volume"

mkdir -p "$MODEL_DIR"

verify_model() {
  model_file="$1"
  actual_size="$(wc -c < "$model_file" | tr -d '[:space:]')"
  [ "$actual_size" = "$MODEL_SIZE_BYTES" ] || fail "model size does not match manifest"
  actual_sha256="$(sha256sum "$model_file" | awk '{print $1}')"
  [ "$actual_sha256" = "$MODEL_SHA256" ] || fail "model checksum does not match manifest"
}

if [ ! -f "$MODEL_PATH" ]; then
  temporary_path="$(mktemp "$MODEL_DIR/.$MODEL_FILENAME.download.XXXXXX")" || fail "could not create model download file"
  cleanup() {
    rm -f "$temporary_path"
  }
  trap cleanup EXIT HUP INT TERM
  if ! wget -q -O "$temporary_path" "$MODEL_DOWNLOAD_URL"; then
    fail "model download failed"
  fi
  verify_model "$temporary_path"
  mv -f "$temporary_path" "$MODEL_PATH"
  trap - EXIT HUP INT TERM
fi

verify_model "$MODEL_PATH"

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
