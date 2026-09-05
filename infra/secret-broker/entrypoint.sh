#!/bin/sh
set -eu

for required in /etc/secrets/broker-ca.pem /etc/secrets/broker-cert.pem /etc/secrets/broker-key.pem; do
  test -r "$required" || { echo "missing broker bootstrap file" >&2; exit 1; }
done

python -m secret_broker.main api &
api_pid=$!
python -m secret_broker.main health &
health_pid=$!
envoy -c /opt/reclaim/infra/secret-broker/envoy.yaml --log-level warning &
envoy_pid=$!

cleanup() {
  kill "$api_pid" "$health_pid" "$envoy_pid" 2>/dev/null || true
  wait "$api_pid" "$health_pid" "$envoy_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

wait -n "$api_pid" "$health_pid" "$envoy_pid"
