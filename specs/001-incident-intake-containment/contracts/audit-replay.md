# Audit, Replay, and Evaluation Contract

## Audit record

Each record carries tenant/case, actor/service, event/action, input and evidence references, policy/model/provider/approval/execution versions, correlation IDs, outcome, timestamp, and append-only integrity linkage. Webhook-derived records additionally retain the verified provider-correlation schema/version, provider event/payment/order identifiers, verification provenance, authoritative mapping reference when resolved, and caller assertion results. Records must be sufficient to replay decisions without implying that a replay performed a live side effect.

## Replay run

Replay input includes fixture version, connector/action simulator versions, the v2.0.0
webhook contract, `VerifiedProviderCorrelation` v1.0.0 data, a trusted authoritative
mapping fixture/reference, policy version, model/provider mode, deterministic seed, and
environment metadata. Mapping fixtures must be seeded from merchant-side order/payment
context; caller-supplied case, incident, tenant, or merchant values may be present only
as assertions. Output includes all stage outcomes, terminal state, mapping resolution
status, differences from expected result, and explicit `replay` label. Missing or
conflicting mapping data must produce the same unresolved/quarantine outcome as live
processing.

## Evaluation record

Each case includes provenance, label source, split, entity/customer grouping identity, temporal boundary, synthetic-overlay lineage, class balance, no-compromise/false-alert classification, mixed legitimate/malicious classification, expected/observed attribution and action outcomes, confidence-interval metadata, and metric references. Apply entity/customer and temporal separation before synthetic overlay generation. Target at least 500 cases when feasible, with 60/20/20 development/validation/sealed-held-out acceptable and at least 100 held-out cases targeted, preferably 150 or more. Held-out seeds/scenarios are sealed from prompts, tuning, and model selection. If fewer cases are available, report actual sample size and statistical limitations without fabricating or padding.

Evaluation reports must include confidence intervals alongside malicious-action precision, recall, contained value, legitimate value disrupted, resolution success, latency, tool efficiency, forbidden attempts/executions, and model cost.
