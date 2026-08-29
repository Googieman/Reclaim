# FS-001 Validation Quickstart

This guide describes the planned validation flow. It is not an implementation script and does not claim that the current repository can execute it yet.

## Prerequisites

- Docker Compose and a running Docker daemon.
- Test-only Razorpay connector configuration, if webhook validation is exercised.
- Keycloak/Vault development configuration with tenant-scoped demo roles/secrets.
- Provider credentials only for an explicitly enabled live model run; replay must work without them.
- The canonical fixture package and labeled evaluation metadata.

## Planned validation flow

1. Start the complete Compose topology and verify health for PostgreSQL, Temporal, Redpanda, Neo4j, MinIO, Redis, Keycloak, Vault, observability, Langfuse, and MLflow.
2. Create or load the one demo merchant tenant and approved connector manifests. Confirm live financial actions are disabled by default.
3. Submit the canonical mixed legitimate/attacker incident fixture through the intake boundary.
4. Verify tenant-scoped case creation, raw evidence checksums, webhook authenticity/quarantine behavior, duplicate acknowledgement, and audit records.
5. Run evidence collection with simulator variants for partial/stale and out-of-order data. Confirm deterministic timeline output and no duplicate facts.
6. Run rules/LightGBM advisory attribution and bounded provider-neutral analysis. Confirm malicious/legitimate/uncertain labels, redaction, typed proposals, and zero model side effects.
7. Evaluate proposals against a pinned policy. Confirm reversible actions may be automatic only when permitted; cancellation/refund/identity restoration remain approval-gated and separation-of-duties is enforced.
8. Execute a permitted reversible action through the Action Gateway. Repeat the request, force an unknown result, reconcile, and verify that no duplicate remote side effect occurs.
9. Force inconclusive verification and irreversible/unresolved exposure. Confirm assigned escalation owner and terminal `escalated_unresolved` state.
10. Re-run the complete flow in labeled replay mode with provider/connector availability disabled. Confirm identical deterministic outputs and explicit replay labeling.
11. Rebuild the Neo4j projection from authoritative events and verify that business correctness remains in PostgreSQL.
12. Validate the benchmark manifest before evaluation: target at least 500 cases when feasible; accept a 60/20/20 split; target at least 100 held-out cases, preferably 150 or more; verify entity/customer and temporal separation before synthetic overlay generation; verify at least 25% no-compromise/false-alert cases and mixed legitimate/malicious activity in at least 30% of compromised cases; confirm held-out seeds/scenarios are inaccessible to prompts, tuning, and model selection. Do not fabricate or pad cases; report actual sample size and statistical limitations.
13. Export evaluation and observability reports with provenance and confidence intervals alongside precision, recall, containment, legitimate disruption, resolution success, latency, tool efficiency, forbidden attempts/executions, and model cost. Record actual p50/p95 latency, throughput, recovery time, and failure rates; compare them with provisional targets without presenting targets as measured baselines.

## Expected evidence

- Case and terminal state traceable to tenant-scoped intake, evidence, timeline, attribution, exposure, policy, approval, action, verification, escalation, and audit records.
- No forbidden action executed; all attempts rejected/quarantined and audited.
- No duplicate financial or non-idempotent side effect.
- Replay/live mode and synthetic/hybrid evaluation labels visible in reports.
- Compose service health, trace correlation, dashboards, logs, and model/evaluation metadata available without exposing secrets or unnecessary PII.
