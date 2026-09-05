# ADR-006: Hosted final-round deployment and private secret delivery

Date: 2026-09-05

Status: proposed implementation design, recorded in response to the user's
explicit request. No runtime, provider, or deployment change has been executed.

## Context

The user requested completion of the full final-round system, with placeholders
in a `secrets/` folder and credentials delivered by an API in another backend
container that is inaccessible to the public. FS-001 already specifies Vault,
tenant-scoped credentials, isolated model/action boundaries, and append-only audit.

A directory named `secrets` is not a security control. Containers do not share a
filesystem automatically, and a private network does not authenticate its callers.
The existing Vault adapter must not be turned into a public credential endpoint.

## Decision

Add `reclaim-secrets`, a stateless Render private service providing one narrowly
scoped read API backed by Vault KV v2. Keep real credentials encrypted in Vault.
The repository's root `secrets/` holds only invalid example values and setup
instructions; populated local files are ignored and excluded from Docker builds.

The broker becomes an explicit trusted credential custodian acting on behalf of
service identities. This extends the physical reader boundary: the broker may
transport Action Gateway credentials, but the Action Gateway is still their sole
application recipient. n8n, the agent, frontend and ordinary API routes gain no
action-credential access. Update the Vault policy tests to reflect delegated
delivery without loosening consumer restrictions.

### Transport and service identity

1. Render has no public route or custom domain for the broker. Compose uses a
   private service network with no published host port for secret delivery.
2. An Envoy TLS listener in the broker container accepts mutual TLS on `8443`.
   Each consumer has a distinct certificate with an exact URI SAN, for example
   `spiffe://reclaim/final/action-gateway`. Never trust a caller-supplied identity.
3. Envoy validates the issuing CA, validity and client-auth usage, strips incoming
   forwarded identity headers, and forwards verified identity to FastAPI bound
   only to `127.0.0.1:9001`. The application rejects absent/unrecognized identity.
   Test that its plaintext port cannot be reached from another container.
4. A separate private health listener on `8081` exposes only boolean liveness and
   readiness for platform probes, which cannot be assumed to present client
   certificates. It has no forwarding path to the secret API.
5. Use `fromService` host discovery plus explicit port `8443`; do not assume the
   platform's discovered health port is the credential listener. Server cert SANs
   must match the actual discovered internal hostname. Never use `verify=false`.
6. Bootstrap CA trust, service certificate/key, and broker Vault auth material are
   deployment-mounted `/etc/secrets/` files. These cannot be fetched from a broker
   that needs the same credentials to authenticate the first request.

Envoy and application processes are supervised as one service: failure of either
terminates the container. Health never reports ready until policy, identity
mapping and Vault connectivity have been validated. Envoy is not an open proxy.

### API contract (new; not implemented yet)

```http
POST /v1/secrets/resolve
Content-Type: application/json

{"secret_id":"razorpay.test.action","tenant_id":"tenant-canonical-demo"}
```

```json
{
  "secret_id": "razorpay.test.action",
  "version": 3,
  "cache_ttl_seconds": 60,
  "values": {
    "key_id": "__REQUIRED_RAZORPAY_TEST_KEY_ID__",
    "key_secret": "__REQUIRED_RAZORPAY_TEST_KEY_SECRET__"
  }
}
```

The response is visible only to the authenticated authorized backend consumer;
the example's strings are deliberately invalid. Cache TTL is a client-use limit,
not a claim that a static provider API key expires or is revoked after 60 seconds.
Never return values to the browser, agent tools, n8n execution data or a case API.

- Request body <= 4096 bytes; reject unknown fields and malformed IDs.
- Identity derives from verified transport. Tenant must be in that identity's
  configured tenant allowlist. Secret ID maps server-side to one exact Vault path.
- No arbitrary paths, URLs, wildcards, secret-listing, bulk dump or write endpoint.
- Non-tenant service secrets use a policy-defined service scope, not an unrestricted
  tenant supplied by the caller. Staging and final credentials have separate paths.
- `401` for missing identity at the application boundary; TLS handshake rejection
  for invalid certs; uniform `403` for forbidden or unknown IDs; `503` for an
  authorized but unavailable secret; `429` for exceeded per-identity limits.
- Return `Cache-Control: no-store`; do not follow redirects. Bound connection and
  request timeout to 2 and 5 seconds, and retry only read transport failures, with
  at most two attempts. Never retry authorization failures.
- Disable automatic API docs, debug exceptions, body/header capture and response
  compression for this API. Secret fields use redacted representations.

### Minimum grant matrix

| Identity | May receive | Must not receive |
|---|---|---|
| `intake-api` | API DB role, evidence storage, webhook verification secret | Razorpay action secret, model provider key, n8n admin key |
| `action-gateway` | Narrow gateway DB role and Razorpay Test Mode action pair | Model provider, n8n admin, other tenants' credentials |
| `model-provider` | Configured LLM provider key, model serving token | Action, business DB and n8n credentials |
| `agent-runner` | No broker grant; only its mounted service identity | Every provider/action/storage secret |
| `event-relay` | Outbox DB role, producer-specific Kafka credential | Approvals, actions and general DB administration |
| `n8n-main`, `n8n-worker` | Own DB/queue credentials, stable n8n encryption key, service-client credential, consumer Kafka credential | RECLAIM business DB, object store, model and gateway credentials |
| `projection-worker` | Graph credential, projection checkpoint DB role, consumer Kafka credential | Actions, model and approval credentials |
| `web-bff` | No broker grant; only mounted session/OIDC bootstrap material | All runtime connector/provider secrets |
| `telemetry-collector` | Write-only telemetry/Langfuse project credentials | Case/action/business DB secrets |
| `evaluator` | MLflow publishing credential, optional restricted HF publishing token | Test Mode action and runtime administration secrets |
| `mlflow-server` | Own DB role, artifact prefix storage credential | Evidence bucket and business DB |
| `deployment-job` | Temporary migration/admin roles and n8n bootstrap key | Runtime access after deployment; remove its grant/cert when finished |

The broker itself uses a renewable Vault credential restricted to the exact
configured paths for the approved tenant/services. No root token, unseal key,
policy-write permission or general KV enumeration enters its container. This is
a high-trust service: compromise can expose its allowed secrets; that residual
risk is not eliminated by mutual TLS.

### Loading, runtime use and rotation

Provision values directly into Vault with an operator identity through secure
administrative access. A planned `scripts/provision-secrets.py` reads a private
input file, validates that required fields are nonempty/non-placeholder, writes
only the approved paths, and prints only IDs/versions. Runtime APIs cannot write
Vault. The input file is optional convenience, never the hosted source of truth.

Trusted backend libraries pull only their named secret bundles. Python services
keep values in memory. For software requiring files, an entrypoint writes only
its allowed subset into a private runtime directory (mode `0700`; files `0600`),
on tmpfs where supported or on the ephemeral service filesystem with the residual
risk documented. No shared secret volume and no bind mount into frontend containers.
Render's `/etc/secrets/` mount is bootstrap input, not this writable directory.

An entrypoint translates its subset into the existing library/n8n settings and
uses `exec` without printing its environment. n8n stores only its allowed API and
Kafka credentials using its own encryption mechanism; secrets must never appear
in workflow JSON or node output. The long-lived n8n encryption key must survive
redeploys and be restored with its DB; rotating it requires an explicit supported
credential re-encryption procedure, not random regeneration at startup.

Use at most 60 seconds' memory caching for action credentials and 300 seconds
for other application keys, bounded by any upstream lease. Refresh expiry is
enforced by each client. After expiry or broker failure, stop new affected work
and record `requires_attention`/escalation; do not fall back to development keys.
Existing unaffected reads may continue. Reconcile an in-flight uncertain provider
action before any retry, including across credential rotation.

Those cache limits apply to broker client reads, not to the lifetime of a static
credential already loaded by third-party software. n8n DB/queue/encryption
configuration remains process configuration until a controlled restart or
supported credential update. Use long-lived scoped credentials there unless a
tested renewal mechanism exists; do not install short Vault leases that expire
inside an unaware n8n process. Rotation must verify every n8n process/credential
reference before revoking the old value. Its encryption key is durable state,
not a 300-second lease.

Rotation publishes a new Vault version, verifies the owning consumer, drains
affected in-flight work, then revokes the old provider credential. Certificate
rotation overlaps trust briefly and tests revocation; use short-lived leaf certs
and a scheduled operator-controlled renewal process. Private CA signing material
and Vault unseal/recovery keys stay outside application containers and ordinary
application backups; keep a separate access-controlled recovery arrangement.
Enforce certificate revocation through a refreshed CRL or an explicit enrolled
certificate denylist in the TLS/policy boundary, and test the refresh delay.

Audit reads/denials/rotation using identity, tenant, secret ID/version, time,
request ID and outcome only. Commit an audit intent before releasing a value; if
required audit cannot be persisted, fail closed. Do not store plaintext secret
values or hashes of low-entropy secrets in the audit. Vault's audit facility is
an additional layer, not a replacement for caller-attribution records.

### Qualification checks

From an external client, broker/private listeners are unreachable and public
routes `/secrets`, `/v1/secrets/resolve`, `/docs`, metrics and encoded proxy
variants do not expose them. From the private network, no-cert, forged-header,
wrong-service, revoked-cert and cross-tenant requests fail. Authorized consumers
receive only their allowed bundle. Root-folder templates never reach built
images. Canary values do not appear in logs, traces, error messages, browser
bundles, session payloads or case API responses. Rotation, broker restart, Vault
outage and restore retain these properties.

## Consequences and alternatives

The broker adds operational dependencies and a high-trust component, but fulfills
the requested private API while retaining Vault instead of inventing an unencrypted
JSON credential store. Direct Vault access alone would be simpler but would not
provide the requested application-owned delivery API. A public secret endpoint,
shared global token, source-controlled real secrets and n8n-based secret delivery
are rejected because they violate the required boundaries.

## References

- [Hosted design](../../../docs/design/hosted-final-round.md)
- [Setup instructions and template meanings](../../../secrets/README.md)
- [Vault TLS certificate authentication](https://developer.hashicorp.com/vault/docs/auth/cert)
- [Render private services](https://render.com/docs/private-services)
- [Render private network](https://render.com/docs/private-network)
- [Render mounted secret files](https://render.com/docs/configure-environment-variables)
