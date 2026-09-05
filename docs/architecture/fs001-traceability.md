# FS-001 implementation traceability

Last validated: 2026-09-04. This document maps the approved functional
requirements to the implementation seams, tests, and observed validation
artifacts. A passing local or deterministic test is not a claim of live
provider, production, benchmark, or deployment qualification.

## Evidence and ownership rules

- PostgreSQL owns business state; n8n owns new durable workflow orchestration through
  allowlisted RECLAIM APIs; Temporal drains existing workflows only; Redpanda transports
  outbox events; Neo4j is a rebuildable projection; Redis is n8n queue coordination only.
  The ownership boundary is implemented in the repositories, migrations, n8n workflows,
  legacy drain profile, event delivery, and projection code.
- Agent/model code produces bounded analysis and typed proposals. Policy is
  deterministic, approvals are separate, and the Action Gateway is the only
  mutation boundary. Replay never invokes a connector or merchant mutation.
- The canonical mixed-activity T130 gate is
  [`tests/acceptance/test_fs001_complete_flow.py`](../../tests/acceptance/test_fs001_complete_flow.py).
  It passed 3 tests locally on 2026-09-02 with one existing LangGraph pending
  deprecation warning.
- Earlier validation records are
  [`fs001-quickstart.md`](../validation/fs001-quickstart.md),
  [`us1-intake-timeline.md`](../validation/us1-intake-timeline.md),
  [`us3-containment.md`](../validation/us3-containment.md), and
  [`performance-baseline.md`](../validation/performance-baseline.md).

## T153 observed evidence — 2026-09-04

The implementation and focused contracts for T153 are present in
[`infra/docker-compose.t153.yml`](../../infra/docker-compose.t153.yml),
[`scripts/validate-t153.ps1`](../../scripts/validate-t153.ps1),
[`tests/acceptance/test_t153_n8n_runtime.py`](../../tests/acceptance/test_t153_n8n_runtime.py),
[`tests/acceptance/test_t153_restart_recovery.py`](../../tests/acceptance/test_t153_restart_recovery.py),
and the dedicated real browser configuration. The focused T153 contract group
passed `41` tests and Ruff passed. The final harness-prepared project
`reclaim-t153-20260904i` recorded a fresh project-owned PostgreSQL volume,
source-built API/web images, one canonical tenant, an `n8n` schema/role owned
by `n8n`, healthy required services, and loopback bindings. The live schema and
safe-runtime test passed; the real browser intake test passed on desktop and
mobile (`2` tests).

The complete T153 run was not promoted. The harness stopped at
`awaiting_n8n_operator_setup` because an operator-created n8n API key and the
activation-only Redpanda/service-token inputs were not available. A real full
browser run observed `1` passing test and `5` failures with workflows inactive
and cases remaining non-terminal. Duplicate delivery, model-unavailability,
worker/API/Redis recovery, and terminal browser results are therefore not
claimed. See [`t153-fresh-volume-n8n.md`](../validation/t153-fresh-volume-n8n.md)
for the sanitized command/result record and exact resume setup. T153 remains
unchecked; T154 and Temporal remain unchanged.

## Requirement mapping

| Requirement | Authoritative implementation | Primary tests | Integration / acceptance evidence | Contract / decision | Limitation or debt |
|---|---|---|---|---|---|
| FR-001 incident intake | `backend/app/intake/service.py`, `backend/api/intake.py` | `tests/contract/test_incident_intake.py`, `tests/acceptance/test_intake_to_timeline.py` | T125 quickstart; T130 stage `incident=accepted` | `contracts/intake-webhook.md`; ADR-001 | Live merchant intake is environment-qualified. |
| FR-002 verified webhook correlation | `backend/app/intake/webhook_processing.py`, `backend/connectors/razorpay/__init__.py`, migrations `005`/`006` | `tests/contract/test_razorpay_webhook.py`, `tests/unit/test_webhook_processing.py`, `tests/integration/test_d3_provider_correlation_postgres.py` | D3 PostgreSQL/RLS evidence in `PROJECT_STATUS.md` | `contracts/intake-webhook.md`; D3 research decision | No live Razorpay or production credentials are claimed. |
| FR-003 tenant-aware cases | `backend/app/db/tenant_context.py`, `backend/app/db/repositories/`, migration `002` | `tests/security/test_fs001_hardening.py`, `tests/integration/test_final_gate_remediation.py` | T130 verifies tenant/case/correlation scope and rejects substitutions | ADR-001; `data-model.md` | Full-stack tenant qualification depends on configured services. |
| FR-004 approved evidence connectors | `backend/connectors/evidence/`, `backend/connectors/simulators/evidence.py`, `backend/evidence/orchestrator.py` | `tests/contract/test_connectors.py`, `tests/integration/test_us1_vertical_slice.py` | T125 canonical evidence and variant coverage | `contracts/connectors.md`; plan Slice 2 | Connectors are deterministic/local unless a merchant-controlled service is configured. |
| FR-005 evidence provenance and untrusted input | `backend/evidence/models.py`, `backend/evidence/storage.py`, `backend/app/storage/minio_evidence.py` | `backend/tests/unit/test_evidence_normalization.py`, `tests/integration/test_remediation_batch_c.py`, `tests/security/test_fs001_hardening.py` | US1 and T125 evidence records preserve checksum/provenance and untrusted classification | `data-model.md` EvidenceItem; ADR-002 | Raw evidence is not a production data-retention claim. |
| FR-006 deterministic timeline | `backend/timeline/reconstruct.py`, `backend/timeline/models.py` | `backend/tests/unit/test_timeline_runtime.py`, `tests/integration/test_us1_vertical_slice.py` | `docs/validation/us1-intake-timeline.md`; T130 stage `timeline=converged` | `data-model.md` TimelineEvent | Live Temporal worker qualification remains environment-dependent. |
| FR-007 duplicate/order convergence | `backend/app/intake/webhook_processing.py`, `backend/timeline/reconstruct.py`, repositories, Action Gateway idempotency | `tests/integration/test_canonical_replay.py`, `tests/integration/test_action_recovery.py`, `tests/integration/test_d3_provider_correlation_postgres.py` | T125 variants; T130 checks no duplicate non-idempotent replay effects | `contracts/events.md`; ADR-001/002 | Full external broker/provider delivery is not asserted by T130. |
| FR-008 rules and LightGBM attribution | `backend/analysis/deterministic_summary.py`, `backend/analysis/` | `tests/contract/test_attribution.py`, `tests/unit/test_deterministic_us2.py`, `tests/acceptance/test_attribution_exposure_analysis.py` | T130 observes rules and LightGBM labels and provenance | `data-model.md` Attribution | The LightGBM path is an advisory fixed local baseline, not production model performance. |
| FR-009 bounded model analysis | `backend/agent/langgraph_harness.py`, `backend/agent/litellm_gateway.py`, `backend/agent/tools.py`, `backend/agent/redaction.py` | `tests/unit/test_analysis_output_parser.py`, `tests/security/test_model_gateway_boundary.py`, `tests/security/test_fs001_hardening.py` | T125/T130 replay path has no model side effect authority | `contracts/analysis-policy.md`; ADR-002 | Hosted provider behavior and live credentials were unavailable. |
| FR-010 distinct labels and uncertainty | `backend/analysis/deterministic_summary.py`, `backend/timeline/reconstruct.py`, `backend/policy/evaluator.py`, `backend/escalation/service.py` | `tests/unit/test_uncertain_attribution.py`, `tests/acceptance/test_attribution_exposure_analysis.py`, T130 | T130 preserves malicious, legitimate, and uncertain activity and escalates inconclusive verification | `data-model.md`; `contracts/analysis-policy.md` | Canonical evidence is synthetic/replay data. |
| FR-011 deterministic exposure | `backend/finance/exposure.py`, `backend/app/db/repositories/finance.py` | `tests/property/test_exposure_invariants.py`, `tests/security/test_refund_safety.py`, `tests/acceptance/test_attribution_exposure_analysis.py` | `docs/validation/us3-containment.md`; T130 checks integer minor units and remaining exposure | `data-model.md` FinancialExposure; constitution III | No production financial outcome is claimed. |
| FR-012 typed defensive proposals | `backend/agent/proposals.py`, `backend/analysis/proposal_validator.py`, `backend/connectors/actions/` | `tests/contract/test_typed_proposals.py`, `tests/security/test_forbidden_proposals.py`, `tests/unit/test_analysis_output_parser.py` | T125 forbidden-proposal variant; T130 verifies simulation/no side effects | `contracts/connectors.md`; ADR-002 | Replay does not exercise a live action connector. |
| FR-013 deterministic policy | `backend/policy/evaluator.py`, `backend/policy/versions.py`, `backend/policy/change_control.py` | `tests/security/test_policy_bounds.py`, `tests/unit/test_us3_runtime.py` | T103/T125 policy outcomes; T130 observes approval-required policy and uncertainty preservation | `contracts/analysis-policy.md`; policy research decision | Live policy-owner configuration is not qualified here. |
| FR-014 reversible automatic actions | `backend/action_gateway/service.py`, `backend/connectors/simulators/actions.py`, `backend/workflows/activities/containment.py` | `tests/integration/test_us3_containment_slice.py`, `tests/unit/test_us3_runtime.py` | `docs/validation/us3-containment.md`; T130 records the reversible action as simulated | ADR-002 | Live action execution remains disabled by default. |
| FR-015 approval and separation of duties | `backend/approvals/service.py`, `backend/api/approvals.py`, `backend/action_gateway/validation.py` | `tests/security/test_approval_separation.py`, `tests/integration/test_us3_action_lifecycle.py` | T103 and T130 observe approved, version-bound, distinct proposer/approver identities | `data-model.md` Approval; approval research decision | No live financial approval or execution is claimed. |
| FR-016 isolated idempotent gateway | `backend/action_gateway/service.py`, `backend/action_gateway/idempotency.py`, `backend/api/control_plane.py` | `tests/contract/test_action_gateway.py`, `tests/integration/test_action_recovery.py`, `tests/security/test_fs001_hardening.py` | T103/T125 and T130 preserve the gateway/simulation boundary | `contracts/action-gateway.md`; ADR-002 | The protected pre-existing contract diff is intentionally unchanged. |
| FR-017 reconcile UNKNOWN before retry | `backend/action_gateway/reconciliation.py`, `backend/action_gateway/state_machine.py` | `tests/integration/test_action_recovery.py`, `tests/integration/test_containment_recovery.py`, `tests/chaos/test_fault_matrix.py` | T126 and T130 observe `reconciled_before_retry` with retry-before-reconciliation false | `contracts/action-gateway.md`; `data-model.md` ActionExecution | External provider reconciliation is not live-qualified. |
| FR-018 verify and use explicit terminal outcomes | `backend/action_gateway/verification.py`, `backend/cases/terminal_states.py` | `tests/unit/test_case_terminal_states.py`, `tests/integration/test_verification_escalation.py`, `tests/integration/test_action_terminal_outcomes.py` | T130 requires verification and observes inconclusive → escalation | `contracts/action-gateway.md`; terminal-outcome research decision | Generic `closed` remains forbidden; live merchant-state reads are not claimed. |
| FR-019 tenant-scoped escalation | `backend/escalation/service.py`, `backend/api/escalations.py`, `backend/cases/terminal_states.py` | `tests/integration/test_verification_escalation.py`, `tests/unit/test_us3_runtime.py`, T130 | T103/T125 evidence and T130 owner, recommendation, remaining exposure, and `escalated_unresolved` | `data-model.md` Escalation | Human follow-up is presented, not performed by the agent. |
| FR-020 append-only audit | `backend/app/audit/chain.py`, `backend/app/audit/actions.py`, `backend/app/audit/model_analysis.py`, migrations | `backend/tests/unit/test_audit_chain.py`, `tests/integration/test_us3_audit_replay_trace.py`, T130 | T125/T130 checksum-linked, tenant/case/correlation-scoped audit chain | `contracts/audit-replay.md`; ADR-001/002 | Observability sinks remain non-authoritative. |
| FR-021 labeled replay/live semantics | `backend/replay/runner.py`, `backend/replay/variants.py`, `backend/replay/mode_selection.py`, `backend/api/replay.py` | `tests/integration/test_canonical_replay.py`, `tests/integration/test_replay_variants.py`, T130 | T125 and T130 verify replay labels, fallback, variants, and no remote side effects | `contracts/audit-replay.md`; ADR-003 | Live mode requires explicit qualified executor and observed live execution. |
| FR-022 tenant isolation and least privilege | `backend/app/auth/oidc.py`, `backend/app/db/tenant_context.py`, `backend/agent/redaction.py`, `infra/security/` | `tests/security/test_fs001_hardening.py`, `tests/security/test_credential_network_boundaries.py`, `tests/integration/test_d3_provider_correlation_postgres.py` | T126–T128 and T130 scope/redaction checks | Constitution VII; ADR-001/002 | Production Redpanda mTLS/SASL/ACL/principal binding remains deployment debt. |
| FR-023 zero forbidden actions | `backend/agent/tools.py`, `backend/agent/proposals.py`, `backend/action_gateway/validation.py`, `infra/security/` | `tests/security/test_forbidden_proposals.py`, `tests/security/test_fs001_hardening.py`, T130 | T127/T128 and T130 reject forbidden proposals and observe zero remote side effects | ADR-002; constitution I/II | This is a deterministic/local safety result, not attacker-interaction testing. |
| FR-024 reviewer-readable provenance | `frontend/src/app/cases/[caseId]/page.tsx`, `frontend/src/components/case/`, `frontend/src/components/audit/`, `frontend/src/lib/api.ts` | `tests/browser/test_operator_workflow.py`, `tests/acceptance/test_quickstart_flow.py`, T130 | T125 UI observation; T130 operator-surface source gate | `quickstart.md`; T122/T123 tasks | In-app browser observation used a local deterministic read-model stub, not a live API. |
| FR-025 evaluation provenance and sealed splits | `evaluation/manifest.yaml`, `evaluation/splitting.py`, `evaluation/sealed_store.py`, `evaluation/runner.py`, `evaluation/metrics.py` | `tests/evaluation/test_dataset_splits.py`, `evaluation/tests/test_holdout_sealing.py`, `tests/evaluation/test_metrics.py` | T125 records zero available cases and sealed controls; T130 trace drops held-out/raw fields | `contracts/audit-replay.md`; ADR-003 | No benchmark corpus exists; target counts are not results and no production metric is claimed. |
| FR-026 structured typed intake | `packages/contracts/intake.py`, `backend/app/intake/service.py`, `frontend/src/components/cases/CaseInbox.tsx` | `tests/contract/test_incident_intake_n8n.py`, frontend typecheck | `/cases` requires source/type/time/narrative and pairs amount/currency | ADR-004; `data-model.md` | UI and service are locally wired; live MinIO qualification remains environment-dependent. |
| FR-027 authoritative intake persistence | `backend/api/main.py`, `backend/api/intake.py`, migration `013_incident_intake_n8n.sql`, `backend/app/intake/raw_report.py` | `tests/integration/test_n8n_intake_boundary.py`, `tests/security/test_n8n_boundary.py` | PostgreSQL UoW, immutable MinIO capture, outbox, request-size middleware | ADR-004; `quickstart.md` | Fresh-volume and external-service gates remain to be run. |
| FR-028 Case Inbox pagination/search | `backend/api/case_inbox.py`, `backend/app/cases/inbox.py`, `backend/app/db/repositories/case_inbox.py` | `tests/unit/test_case_inbox.py`, `tests/security/test_n8n_boundary.py` | Cursor order and identifier-only query are explicit | `case_inbox.py` contract | Query execution needs live PostgreSQL validation. |
| FR-029 n8n API-only handoff | `infra/n8n/workflows/incident-analysis-handoff.v1.json`, `backend/api/orchestration.py` | `tests/integration/test_n8n_workflows.py`, `tests/security/test_n8n_boundary.py` | Kafka Trigger → claim → normalize → typed analysis → handoff | ADR-004; n8n README | Kafka credential import and end-to-end worker recovery remain environment-dependent. |
| FR-030 allowlisted orchestration stages | `packages/contracts/orchestration.py`, `backend/app/orchestration/service.py`, migration `013_incident_intake_n8n.sql` | `tests/contract/test_incident_intake_n8n.py`, `tests/unit/test_orchestration.py` | expected-state/idempotency required; stage enum is allowlisted | ADR-004 | Stage conflict behavior still requires live transaction coverage. |
| FR-031 bounded failure recovery | `infra/n8n/workflows/incident-analysis-error-recovery.v1.json`, `backend/app/orchestration/service.py` | `tests/unit/test_orchestration.py`, `tests/integration/test_n8n_workflows.py` | `requires_attention` is explicit; replay fallback is not used | ADR-004 | External n8n restart recovery remains environment-dependent. |
| FR-032 inbox-centered operator flow | `frontend/src/app/cases/page.tsx`, `frontend/src/components/cases/CaseInbox.tsx`, `frontend/src/app/cases/[caseId]/page.tsx` | `tests/browser/test_case_inbox.py`, frontend typecheck/lint/build | `/` redirects to `/cases`; intake row links to existing case view | `quickstart.md`; DESIGN.md | Browser flow requires the local Compose stack. |

## Orchestration migration trace

| Migration step | Artifact | Exit evidence |
|---|---|---|
| New-case cutover | `backend/app/config.py`, `infra/docker-compose.yml`, `infra/n8n/workflows/incident-analysis-handoff.v1.json` | `RECLAIM_ORCHESTRATION_PROVIDER=n8n`; new cases have n8n workflow version |
| Legacy drain | Compose `legacy-temporal` profile and existing Temporal tests | No new incident routes to Temporal; existing run inventory is empty |
| Removal gate | ADR-004 and project status | parity, duplicate delivery, restart recovery, fresh-volume, and security gates pass before deleting SDK/workflow code |

## T130 observed complete-flow evidence

The canonical fixture is `tests/fixtures/canonical/incident.json` and is
explicitly replay-labelled. T130 observed:

- all 14 declared stages had non-empty outcomes;
- malicious, legitimate, and uncertain activity stayed distinct;
- INR exposure was calculated in integer minor units with explicit contained,
  recoverable, legitimate-disruption, and remaining-exposure fields;
- policy required approval, the approval was approved under the expected policy
  version, and proposer/approver identities were distinct;
- action identities, action types, and target resources matched the fixture;
- replay action output was simulated, with no remote side effects and no live
  execution;
- UNKNOWN was reconciled before retry, verification was mandatory, and
  inconclusive verification escalated to `escalated_unresolved`;
- audit records were tenant/case/correlation scoped and checksum-linked; and
- forbidden replay proposals were rejected, while tenant and case substitutions
  were rejected before processing.

These observations qualify the deterministic/Test Mode path only. They do not
prove live Razorpay, hosted model, full Compose, production Redpanda security,
or benchmark performance.
