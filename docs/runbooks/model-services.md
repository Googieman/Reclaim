# Model services runbook

RECLAIM has two separate model profiles:

- `reclaim-specialist` is the investigation profile. It receives only the
  bounded evidence representation and fixed read/proposal tools. Its output is
  advisory typed analysis; it cannot write PostgreSQL, call the Action Gateway,
  execute shell/network operations, or approve an action.
- `reclaim-help-deepseek` is the documentation-help profile. It receives a
  normalized question and reviewed documentation passages only. It has no case
  lookup, database, shell, web, arbitrary-network, credential, or business-action
  capability.

## Help model bundle

The candidate artifact is `DeepSeek-R1-Distill-Qwen-1.5B-Q4_0-GGUF`, served by a
pinned llama.cpp image. The manifest records upstream revision, SHA-256, size,
quantization, license references, runtime digest, and bounded context/output
limits in [`models/help-deepseek/manifest.json`](../../models/help-deepseek/manifest.json).
The preparation script writes only to an operator-selected external artifact
directory and refuses an existing checksum mismatch unless explicitly forced.

Weights are not committed, downloaded, or assumed to exist. The model service is
private, authenticated, tool-disabled, web-UI-disabled, concurrency-one, and
disabled by default (`RECLAIM_HELP_ENABLED=false`). The checked-in Railway file
is a deployment proposal, not deployment evidence. Do not provision billable
resources without an authorized resource decision and record of the resulting
startup, memory, disk, latency, and reliability measurements.

## Help request path

`POST /help/chat` requires a verified bearer identity, tenant scope, and reviewer
role. Case-aware help is deliberately rejected in this version. Retrieval is a
deterministic allowlist from [`docs/help/index.json`](../help/index.json); the
public response includes only reviewed source references and a final answer.
Missing evidence, malformed citations, private reasoning markers, timeout, or
model unavailability becomes an explicit `insufficient_evidence` or `unavailable`
status. No transcript is persisted.

## Qualification commands

```powershell
python -m pytest backend/tests/unit/test_help_chat.py backend/tests/contracts/test_help_chat_api.py backend/tests/security/test_help_chat_boundaries.py tests/contract/test_help_model_gateway.py -q
python scripts/evaluate_help_chat.py --dataset evals/help-chat/questions.jsonl --output evals/help-chat/reports/local.json
```

The offline evaluator exits with a resource-blocked status and `metrics: null`.
Use a real authenticated endpoint only when it is explicitly authorized; never
convert a missing endpoint or synthetic fixture into a quality result.

## Hosted dashboard help-chat deployment

Task 5 documents the Railway configuration; the checked-in configuration is not
deployment or smoke evidence. The verified public services are:

- Frontend: `https://marvelous-truth-production-5c3d.up.railway.app`
- API: `https://reclaim-production-b5df.up.railway.app`

The public browser path is frontend → API. The API then calls the private
Railway `model-gateway` service, which calls the private Railway `model-help`
service. Neither private service gets a public domain or browser URL. Do not
point the browser at either private service or expose the model health or
completion endpoints publicly.

### Exact Railway variables

Set non-secret values exactly as shown. Values marked `secret` are variable
names only; enter their values through Railway's secret-variable UI and never
commit or print them.

API service (`Reclaim`):

```text
RECLAIM_HELP_CHAT_ENABLED=true
RECLAIM_HELP_CHAT_PROFILE=reclaim-help-deepseek
RECLAIM_HELP_GATEWAY_BASE=<private model-gateway service URL>
RECLAIM_LIVE_ACTIONS_ENABLED=false
RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED=false
RECLAIM_HELP_GATEWAY_TOKEN=<secret>
```

Gateway service (`model-gateway`, private):

```text
RECLAIM_HELP_API_BASE=<private model-help service URL>/v1
RECLAIM_HELP_GATEWAY_TOKEN=<secret>
MODEL_API_KEY=<secret>
```

Model service (`model-help`, private):

```text
MODEL_PATH=/models/deepseek-r1-distill-qwen-1.5b-q4_0.gguf
MODEL_MANIFEST_PATH=/etc/reclaim/help-model-manifest.json
MODEL_FILENAME=deepseek-r1-distill-qwen-1.5b-q4_0.gguf
MODEL_REPOSITORY=ggml-org/DeepSeek-R1-Distill-Qwen-1.5B-Q4_0-GGUF
MODEL_REVISION=fc9d48f477cfe8f983fa5e41557ecd47e619fef4
MODEL_SHA256=0d3f4820ee66ab44884b8176f17371eb1baa1d63df15740ffd5873d9e03e8978
MODEL_SIZE_BYTES=1066227008
MODEL_DOWNLOAD_URL=https://huggingface.co/ggml-org/DeepSeek-R1-Distill-Qwen-1.5B-Q4_0-GGUF/resolve/fc9d48f477cfe8f983fa5e41557ecd47e619fef4/deepseek-r1-distill-qwen-1.5b-q4_0.gguf?download=true
PORT=8080
MODEL_API_KEY=<secret>
```

The model service uses the persistent Railway volume `help-model-data` mounted
at `/models`. Railway health checks must use port `8080` and path `/health`.
The service starts only after the artifact matches the manifest's filename,
revision, SHA-256, and byte size. The corresponding manifest identity is
`reclaim-help-deepseek` / `DeepSeek-R1-Distill-Qwen-1.5B-Q4_0-GGUF`, revision
`fc9d48f477cfe8f983fa5e41557ecd47e619fef4`, SHA-256
`0d3f4820ee66ab44884b8176f17371eb1baa1d63df15740ffd5873d9e03e8978`, and
`1066227008` bytes (`Q4_0`). Model weights are not stored in Git.

### Operator boundary and safe verification

The `/help/chat` route requires a verified bearer identity, tenant scope, and
reviewer role. Ask only a reviewed documentation question when a hosted smoke
run is authorized; for example, `What does the release preflight conditional
no-go decision mean?` Verify the answer has reviewed source references, then
verify that an unsupported question produces a safe abstention. Do not record
either result as observed until the deployment-owned Task 7 run is complete.

The help icon and assistant are strictly documentation-only. They do not inspect
case records, call connectors, perform payments, refunds, cancellations,
approvals, account mutations, database writes, shell commands, arbitrary network
calls, or other business-state changes. This preserves RECLAIM's defense-only
boundary for merchant-controlled systems and approved connectors.
