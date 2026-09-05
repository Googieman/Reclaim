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
