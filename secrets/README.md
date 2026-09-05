# RECLAIM secret setup

These files are **examples for a planned integration**, not active credentials or
a working secret loader. The private broker and provisioning commands still need
implementation according to the [completion plan](../docs/superpowers/plans/2026-09-05-hosted-final-round-completion.md).

## Which file means what

| File | Purpose |
|---|---|
| `runtime.example.json` | Named secret bundles and their permitted backend consumers |
| `bootstrap.example.json` | Initial container identity, Vault authentication and deployment-only inputs |
| `access-policy.example.json` | Deny-by-default service/tenant-to-secret mapping; no secret values |
| `deployment.example.json` | Non-secret provider endpoints, environment choices and deployment settings |

Never replace placeholders inside a tracked example. Provision values into Vault
directly, or copy the required example to an ignored `*.local.json` in this folder
using your editor. Examples and real local files are excluded from Docker builds.
Git ignores every file under this folder except this README and the four named
examples. Git ignore is not encryption: restrict local file permissions and do not
upload populated local files, terminal transcripts or screenshots to the chat.

All strings beginning `__REQUIRED_` or `__OPTIONAL_` are intentionally invalid.
`template_only: true` is another rejection marker. The future loader must reject
template files; a populated private input sets it to false and enables only the
configured integrations. Optional integrations need no credential until enabled;
enabled integrations with missing values must fail closed.

## First items to prepare

1. The **n8n owner/API key** for T153 workflow bootstrap. This is currently the
   first external setup dependency recorded in the repository.
2. **One LLM provider account/key**, unless using an independently qualified
   authenticated specialist endpoint. Choose an explicit model and usage cap.
3. A **Render workspace, region and spending limit**, with GitHub access to
   `Googieman/Reclaim`. The full topology includes paid private services/workers.
4. **Razorpay Test Mode keys** if the final demonstration will include real
   provider API calls. The simulator requires no Razorpay credentials.

Infrastructure accounts can be prepared while local lifecycle/model work runs.
The runtime expects actual TLS endpoints and scoped service users; a list of API
keys alone does not provision these dependencies.

## How to obtain each credential

### n8n

Log in as the owner of the intended n8n instance. Open **Settings -> n8n API ->
Create an API key**, choose a label such as `reclaim-bootstrap` and an expiration,
then save the key privately as `n8n.bootstrap.values.api_key`. The public REST API
uses the `X-N8N-API-KEY` header. API scopes depend on edition; do not assume a
Community key is narrowly scoped. Keep this administrative key in the deployment
job only and revoke it after bootstrap/qualification when no longer needed.
[Official n8n authentication guide](https://docs.n8n.io/connect/n8n-api/authentication)

This admin API key differs from the **RECLAIM n8n service credential**, used by
workflow nodes to call RECLAIM. Create a dedicated OIDC service client with only
the tenant's orchestrator role. The hosted bootstrap will configure OAuth2 client
credentials and token refresh; the existing local harness temporarily accepts
`RECLAIM_N8N_SERVICE_TOKEN`. Never substitute a human approver/admin token.

The local T153 owner setup uses its loopback editor. Hosted n8n remains private;
operator access must use an authenticated restricted administration ingress with
an upstream fixed to n8n, then disable that ingress after setup if unnecessary.
It must never proxy Vault or the secrets broker. Owner account setup and key
creation need a real operator login; this plan does not invent those values.

### Model provider

For OpenAI as one supported provider choice, sign in to the API platform, select
a project, create an API key and save it in `model.provider.values.api_key`.
Set the selected LiteLLM provider/model in `deployment.local.json`; confirm API
usage/billing is available and enforce an application-side request/token/cost cap.
Only the trusted provider gateway receives this key. The LangGraph agent runner
calls that gateway through its service identity and never sees the provider key.
[OpenAI API key setup](https://developers.openai.com/api/docs/quickstart)

Other providers can use the same named bundle after their adapter and strict
output format are tested. Credentials for an authenticated specialist endpoint
belong in `model.serving`; a public or unauthenticated endpoint is not assumed.

### Razorpay Test Mode

As the merchant account owner/admin, open Razorpay Dashboard, select **Test Mode**,
then **Account & Settings -> API Keys -> Generate Key**. Save the Key ID and Key
Secret privately in `razorpay.test.action`. The test Key ID should begin
`rzp_test_`; the secret is visible when generated. Never supply Live Mode keys.
[Razorpay key generation](https://razorpay.com/docs/payments/dashboard/account-settings/api-keys/)

For webhooks, use **Account & Settings -> Webhooks -> Add New Webhook**. Once the
hosted endpoint exists, register its exact HTTPS URL and required events. Generate
a separate random webhook signing secret and save the same value in Razorpay and
`razorpay.test.webhook`. This is not the API Key Secret. Preserve old webhook
verification versions through the documented retry window during rotation.
[Razorpay setup and webhooks](https://razorpay.com/docs/payments/quickstart/)

The current adapter has no HTTP transport. Implementation and approval,
reconciliation and verification tests are required before these credentials are
used. Test Mode refunds may only reference captured test payments and their
original source. Merchant session/fulfillment actions stay on the corresponding
simulators unless separately implemented; they are not invented Razorpay APIs.

### Redpanda/Kafka

Create/select a cluster. Record its connection endpoints and authentication mode.
Create distinct producer, n8n consumer and projection consumer users and grant
only their required topic/group operations. Put each username/password and issued
TLS material in its `kafka.*` bundle. A Redpanda Cloud management API credential
is not a Kafka SASL password. [Redpanda authorization](https://docs.redpanda.com/cloud-data-platform/security/authorization/)

Current ADR-005 requires SASL_SSL **and client certificates**. Confirm the chosen
provider/tier supports that combination before paying. If it does not, record a
reviewed architecture amendment and test the alternative; do not fill certificate
fields with dummy values or silently turn certificate validation off.

### S3-compatible storage

Create a private evidence bucket and a separate model-artifact bucket/prefix.
Create a service identity with only required bucket/prefix operations; give the
API evidence credentials and MLflow its own artifact credentials. Record endpoint,
region, bucket and any supported retention/versioning requirements. For AWS IAM,
an IAM user can generate an access key from its **Security credentials** tab;
use workload federation instead where the selected deployment supports it.
[AWS access-key instructions](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-key-self-managed.html)

Put evidence credentials in `api.evidence` and artifact credentials in
`mlflow.artifacts`. The existing MinIO adapter must pass immutable-write/checksum
tests against the chosen provider before compatibility is claimed. Do not grant
the runtime bucket deletion or general account administration.

### PostgreSQL and Key Value

These are connection credentials rather than third-party API keys. The deployment
job provisions separate API, gateway, outbox, projection, audit, n8n, Keycloak and
MLflow roles/databases as needed and writes the resulting runtime bundles to
Vault. Render's administrative connection belongs only to the migration/provision
job. Application services obtain their own credentials from the broker.

Use private connection endpoints and supported TLS. n8n main/worker share their
queue identity and stable encryption key, but never the RECLAIM business DB role.
Key Value eviction/durability and n8n Redis client TLS compatibility need a real
queue/restart test before release.

### OIDC and Vault

Create a `reclaim` realm/application, exact frontend redirect/logout URLs, a web
client, an API audience and dedicated service clients. Create separate reviewer,
approver and escalation-owner users/roles with a tenant claim. Issuer/JWKS/audience
are public configuration, not secret keys. Web session encryption/OIDC client
material goes only to the server-side BFF bootstrap; service-client secrets go to
the owning backend bundle.

Vault is initialized/unsealed by an operator, with per-environment KV storage,
TLS, certificate auth, least-privilege policies and audit enabled. Issue the broker
a renewable scoped auth identity. Its certificate/key and CA trust are deployment
bootstrap files. Root tokens, CA signing keys and unseal/recovery shares remain in
the operator's secure custody. [Vault certificate auth](https://developer.hashicorp.com/vault/docs/auth/cert)

### Neo4j, Langfuse, MLflow and telemetry

- Neo4j: create the database and a projection-specific user; save its password in
  `projection.neo4j` and the TLS URI in deployment configuration. A cloud account
  management token is not the database password.
- Langfuse: create a project, then open **Project -> Settings** to create its
  public/secret API key pair. Store both in `telemetry.langfuse`; supply the project
  host separately. [Langfuse key locations](https://langfuse.com/faq/all/where-are-langfuse-api-keys)
- Managed telemetry: create write credentials for the selected metrics/logs/traces
  destinations and place them in `telemetry.export`. Grafana dashboard/admin
  credentials must not be used as general ingestion credentials.
- MLflow: configure the private tracking server's own DB/artifact credentials and
  an authenticated publishing identity for the evaluator. `tracking_token` denotes
  the planned auth-gateway token; it is not a claim that a bare MLflow server
  automatically issues API keys. Record the chosen auth mechanism during setup.

### Hugging Face / training (when needed)

Open **Settings -> Access Tokens -> New token** and use a fine-grained token
restricted to the intended model repository. Separate read/inference access from
artifact publishing; training jobs keep their own compute-provider credentials.
No HF token is required just to run locally available ungated weights. The optional
`training.huggingface` bundle is for a restricted publishing job, never the UI,
n8n or Action Gateway. [Hugging Face token guide](https://huggingface.co/docs/hub/security-tokens)

### Render / GitHub deployment access

Connect the GitHub repository in Render. Plugin OAuth or interactive CLI login
can provide deployment access; a separate Render API key is only needed for the
chosen CLI/CI automation. It belongs in the deployment runner's secret store,
never in any RECLAIM application container or runtime broker response. No GitHub
personal access token is required in application runtime.

## How the private delivery will work

An operator provisions Vault. Render mounts each container's distinct identity
under `/etc/secrets/`. The backend authenticates with mutual TLS to the private
broker, requests one named bundle, and receives only the fields allowed for its
identity/tenant. It uses them in memory or a private runtime file if required.
Application containers never share this source folder. The agent and browser
have no secret-reading grant. [Render secret-file mounting](https://render.com/docs/configure-environment-variables)

The loader/provisioning script, access checks, rotation, outage handling and
no-public-access tests are deliverables in the plan, not implemented behavior
of these examples. See [ADR-006](../specs/001-incident-intake-containment/decisions/ADR-006-hosted-secret-delivery.md)
for the API and exact security boundary.
