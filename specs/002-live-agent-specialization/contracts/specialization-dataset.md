# Specialization Dataset Contract

The training builder emits JSONL chat rows plus a manifest. Every row must have:

```json
{
  "example_id": "example-...",
  "messages": [
    {"role": "user", "content": "{...bounded case context...}"},
    {"role": "assistant", "content": "{...typed advisory response...}"}
  ],
  "provenance": {
    "case_source": "...",
    "fixture_version": "...",
    "data_class": "synthetic",
    "scenario_family": "mixed_legitimate_malicious",
    "compromise_status": "compromised",
    "split": "development",
    "generation_version": "reclaim-dataset-v1.0.0",
    "label_version": "deterministic-analysis-v1.0.0",
    "entity_group_id": "entity-...",
    "customer_group_id": "customer-...",
    "temporal_boundary": "2026-09-01T09:00:00Z"
  }
}
```

The assistant content must validate against the existing analysis response/proposal contract after request binding. It may include concise operational rationale and evidence references. It must not include model-supplied amounts/currency, hidden chain-of-thought, credentials, secrets, arbitrary network/tool instructions, or unsupported actions.

The manifest records source checksum, row checksum, split counts, class balance, leakage checks, validation errors, and held-out seal metadata. The validator fails closed on duplicates, invalid references, unknown resources, unsupported actions, financial inconsistency, secrets/needless PII, or split overlap.
