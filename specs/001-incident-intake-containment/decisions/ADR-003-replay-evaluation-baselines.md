# ADR-003: Deterministic Replay, Grouped Evaluation, and Honest Baselines

**Status**: Accepted for FS-001 planning
**Date**: 2026-08-30

## Context

FS-001 must demonstrate a complete flow when external providers are unavailable and compare interchangeable model providers fairly. No held-out dataset, baseline, or production metric currently exists.

## Decision

Use the same versioned connector/action contracts for live and deterministic simulator runs. Maintain one canonical end-to-end fixture plus explicit security, ordering, failure, approval, reconciliation, verification, escalation, and provider-unavailability variants. Target a benchmark corpus of at least 500 cases when feasible; a 60% development, 20% validation, and 20% sealed held-out split is acceptable, with at least 100 held-out cases targeted and 150 or more preferred. Perform leakage-safe entity/customer and temporal separation before synthetic overlay generation. Require at least 25% no-compromise/false-alert cases and mixed legitimate/malicious activity in at least 30% of compromised cases. Keep held-out seeds/scenarios inaccessible to prompts, tuning, and model selection. Do not fabricate or pad cases; report actual sample size, confidence intervals, and statistical limitations. Treat p95 simulator intake acknowledgement <=2 seconds and canonical replay completion <=5 minutes as provisional targets only; publish measured p50/p95 latency, throughput, recovery time, failure rates, and required safety metrics with provenance.

## Consequences

Replay is labeled and cannot be represented as live production fraud performance. Related records cannot cross evaluation splits. Dataset shortages and uncertainty are reported rather than padded or hidden. Release thresholds require a documented baseline.

## Rejected alternatives

Happy-path-only replay, event-level random splits, provider-specific evaluation inputs, and unmeasured performance claims were rejected because they permit leakage or overclaim system capability.
