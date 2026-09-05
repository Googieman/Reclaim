# FS-001 Validation Quickstart

This guide covers the localhost n8n-backed intake and Case Inbox path as well as the
legacy replay qualification path. Both remain simulation-only and do not authorize
live merchant or financial actions.

## Runnable n8n-backed localhost flow

From PowerShell at the repository root:

```powershell
.\scripts\start-demo.ps1
```

The command builds the API and web images locally, starts PostgreSQL, Redpanda, Redis,
MinIO, and the n8n main/worker pair, initializes the isolated n8n schema, and waits for
the ingress services to become healthy. Open `http://127.0.0.1:3000/cases` and use
**New incident intake**. Run `.\scripts\status-demo.ps1` for readiness and
`.\scripts\stop-demo.ps1` to stop containers without deleting the database volume.

After creating the local n8n owner and API key in the n8n UI, set `N8N_API_KEY`,
`N8N_KAFKA_CREDENTIAL_DATA_JSON`, and `RECLAIM_N8N_SERVICE_TOKEN` from the
current-process secret source only. Then import and activate the versioned
workflows with:

```powershell
.\infra\n8n\bootstrap.ps1 -N8nBaseUrl http://127.0.0.1:5678 -Activate
```

The bootstrap is idempotent and fails closed when the operator key or activation
credentials are absent; it never scrapes or invents credentials.

For the isolated T153 gate, use the two phases below instead of the shared
`reclaim-demo` project:

```powershell
.\scripts\validate-t153.ps1 -Prepare -ProjectName reclaim-t153-<unique-suffix>
# Complete the printed n8n owner/API-key setup if requested.
.\scripts\validate-t153.ps1 -Run -ProjectName reclaim-t153-<same-suffix>
```

The T153 harness uses only its validated project and preserves the project and
volumes on failure. It does not modify or clean up `reclaim-demo`.

Expected visible behavior:

- `/cases` is the primary tenant-scoped inbox, with state and automation filters,
  identifier-only search, cursor pagination, and no narrative search.
- The intake panel requires source, incident type, occurred time, and narrative;
  optional amount/currency is stored as integer minor units and marked unverified.
- An accepted intake creates one PostgreSQL incident/case, one immutable MinIO raw
  report, and one `incident.accepted` outbox record. Repeating the idempotency identity
  returns the original incident and case.
- n8n claims the event with its execution ID, calls only the RECLAIM APIs, and stops at
  `awaiting_human`. A model/API failure becomes `requires_attention`; replay is never
  silently substituted.
- The new case row is highlighted and links to the existing case view, which shows
  typed intake metadata and orchestration state. Approval and execution remain explicit
  operator actions, and no live merchant side effects occur.

## Legacy replay flow

Use `docker compose --profile legacy-temporal` only to drain or inspect pre-existing
Temporal runs. New incident intake is not routed to that profile. The replay fixture
continues to provide the deterministic, explicitly labeled case workspace when provider
or connector qualification is unavailable.

## Prerequisites

- Docker Compose and a running Docker daemon.
- Test-only Razorpay connector configuration, if webhook validation is exercised.
- Keycloak/Vault development configuration with tenant-scoped demo roles/secrets.
- Provider credentials only for an explicitly enabled live model run; replay must work without them.
- The canonical fixture package and labeled evaluation metadata.

## Production qualification flow

1. Start the complete Compose topology and verify health for PostgreSQL, Redpanda, Redis, MinIO, n8n main/worker, Neo4j, Keycloak, Vault, observability, Langfuse, and MLflow. Start the `legacy-temporal` profile only when validating the drain path.
2. Create or load the one demo merchant tenant, approved connector manifests, and
   trusted provider-correlation mappings from merchant order/payment context. Confirm
   live financial actions are disabled by default.
3. Submit the canonical mixed legitimate/attacker incident fixture through the intake boundary.
4. Verify tenant-scoped case creation, raw evidence checksums, webhook authenticity,
   v2.0.0 provider-correlation derivation, authoritative mapping resolution,
   assertion-only case/incident IDs, unresolved/cross-tenant quarantine, duplicate
   acknowledgement, and audit records.
5. Verify the `incident.accepted` Redpanda delivery, n8n execution claim, duplicate delivery behavior, API-only credentials, and authoritative orchestration run. Run evidence collection with simulator variants for partial/stale and out-of-order data. Confirm deterministic timeline output and no duplicate facts.
6. Run rules/LightGBM advisory attribution and bounded provider-neutral analysis. Confirm malicious/legitimate/uncertain labels, redaction, typed proposals, and zero model side effects.
7. Evaluate proposals against a pinned policy. Confirm reversible actions may be automatic only when permitted; cancellation/refund/identity restoration remain approval-gated and separation-of-duties is enforced.
8. Execute a permitted reversible action through the Action Gateway. Repeat the request, force an unknown result, reconcile, and verify that no duplicate remote side effect occurs.
9. Force inconclusive verification and irreversible/unresolved exposure. Confirm assigned escalation owner and terminal `escalated_unresolved` state.
10. Re-run the complete flow in labeled replay mode with provider/connector
    availability disabled and the same trusted mapping fixture. Confirm identical
    deterministic correlation, association, quarantine, and downstream outputs and
    explicit replay labeling.
11. Rebuild the Neo4j projection from authoritative events and verify that business correctness remains in PostgreSQL.
12. Validate the benchmark manifest before evaluation: target at least 500 cases when feasible; accept a 60/20/20 split; target at least 100 held-out cases, preferably 150 or more; verify entity/customer and temporal separation before synthetic overlay generation; verify at least 25% no-compromise/false-alert cases and mixed legitimate/malicious activity in at least 30% of compromised cases; confirm held-out seeds/scenarios are inaccessible to prompts, tuning, and model selection. Do not fabricate or pad cases; report actual sample size and statistical limitations.
13. Export evaluation and observability reports with provenance and confidence intervals alongside precision, recall, containment, legitimate disruption, resolution success, latency, tool efficiency, forbidden attempts/executions, and model cost. Record actual p50/p95 latency, throughput, recovery time, and failure rates; compare them with provisional targets without presenting targets as measured baselines.

## Expected evidence

- Case and terminal state traceable to tenant-scoped intake, evidence, timeline, attribution, exposure, policy, approval, action, verification, escalation, and audit records.
- No forbidden action executed; all attempts rejected/quarantined and audited.
- No duplicate financial or non-idempotent side effect.
- Replay/live mode and synthetic/hybrid evaluation labels visible in reports.
- Compose service health, trace correlation, dashboards, logs, and model/evaluation metadata available without exposing secrets or unnecessary PII.
