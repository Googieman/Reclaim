# Model Profile and Evaluation Contract

## Logical profiles

- `reclaim-specialist`: open-weight RECLAIM SFT artifact served locally through an OpenAI-compatible endpoint.
- `reclaim-baseline`: unmodified open-weight base model through the same provider interface.
- `reclaim-cloud-fallback`: optional explicitly configured LiteLLM provider used only when policy/configuration permits.

The profile resolver returns provider/model/mode/version and configuration references. It does not return secret values. A fresh profile uses provider mode `live`; replay uses the existing replay provider and is never selected as an implicit fresh fallback.

## Evaluation record

Each profile is evaluated with the same manifest, bounded request context, system prompt, tool registry, budget, deterministic analysis/policy inputs, parser, proposal validator, and evaluator version. The report must include:

- attribution precision/recall and macro F1 where meaningful for malicious/legitimate/uncertain labels;
- schema-valid and evidence/reference-valid rates;
- supported, forbidden, unnecessary, and policy-valid proposal rates;
- fabricated evidence/resource and prompt-injection failure rates;
- legitimate value disrupted and other false-positive cost measures;
- latency, failures, token count, and cost when available;
- actual sample counts, split/provenance, confidence intervals or limitations, and SHIP/DON'T SHIP.

DPO is `skipped` unless legitimate human/deterministic preference pairs exist and pass validation. SFT is the first training method.
