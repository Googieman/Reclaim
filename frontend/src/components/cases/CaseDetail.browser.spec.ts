import { expect, test } from "@playwright/test";

const modePayload = {
  requested_mode: "live",
  effective_mode: "live",
  final_mode: "live",
  provider_available: true,
  connector_available: true,
  provider_qualified: true,
  connector_qualified: true,
  live_execution_occurred: false,
  live_actions_enabled: false,
  live_financial_actions_enabled: false,
  availability_reasons: [],
  fallback_reason: null,
  label: "fresh_agent",
  simulation_notice: "Fresh Agent analysis + Action Gateway Simulator/Test Mode",
  decision_version: "local-authoritative-demo-v1.0.0",
};

const baseView = {
  case: {
    case_id: "case-001",
    tenant_id: "demo-tenant",
    incident_id: "incident-001",
    merchant_name: "Northstar merchant",
    state: "analyzed",
    owner_id: null,
    severity: "high",
    last_refreshed_at: "2026-09-03T09:05:00Z",
  },
  reported_incident: null,
  orchestration: null,
  timeline: [],
  exposure: {
    currency: "INR",
    gross_exposure_minor: 125000,
    recoverable_value_minor: 125000,
    contained_value_minor: 0,
    legitimate_value_disrupted_minor: 0,
    irreversible_loss_minor: 0,
    remaining_exposure_minor: 125000,
    calculation_version: "exposure-v1.0.0",
    source_references: [],
    by_currency: [],
  },
  proposal: null,
  policy_decision: null,
  approval: null,
  action: null,
  verification: null,
  escalation: null,
  audit: [],
  mode: modePayload,
  evaluation: null,
  read_only: false,
  authoritative: true,
  remote_side_effects: [],
  agent_analysis: null,
};

const persistedAgentAnalysis = {
  analysis_id: "analysis-001",
  run_id: "run-001",
  status: "completed",
  mode: "live",
  provider: "qualified-provider",
  model: "qualified-model",
  uncertainty: ["Payment ownership remains uncertain."],
  attributions: [],
  refusal_records: [],
  provenance: {
    authoritative_store: "postgresql",
    request_checksum: "request-checksum",
    response_checksum: "response-checksum",
    deterministic_analysis_checksum: "deterministic-analysis-checksum",
    deterministic_exposure_checksum: "deterministic-exposure-checksum",
  },
};

const proposal = {
  proposal_id: "proposal-001",
  action_type: "refund",
  target_resource: "payment-001",
  amount_minor: 125000,
  currency: "INR",
  rationale: "Contain the confirmed unauthorized payment.",
  evidence_references: ["event-001"],
  canonical_action_id: "action-001",
  current_resource_state: "captured",
  reversibility: "reversible simulator action",
  customer_impact: "low; simulator only",
  proposer_id: "analysis:analysis-001",
};

const policyDecision = {
  result: "approval_required",
  policy_version_id: "policy-v1",
  evaluator_version: "evaluator-v1",
  evaluated_at: "2026-09-03T09:06:00Z",
  reason: "Independent approval required.",
  evaluated_conditions: {},
};

const pendingApproval = {
  approval_id: "approval-001",
  request_id: "request-001",
  status: "pending",
  proposer_id: "analysis:analysis-001",
  approver_id: null,
  approver_role: "independent_approver",
  policy_version_id: "policy-v1",
  expected_version: 0,
  expires_at: "2026-09-03T10:00:00Z",
  reason: "Independent authenticated approver required.",
};

const approvedApproval = { ...pendingApproval, status: "approved", approver_id: "reviewer-001" };

const actionLifecycle = {
  status: "completed",
  execution_id: "execution-001",
  idempotency_key: "idempotency-001",
  reconciliation_state: "reconciled",
  verification_state: "verified",
  remote_reference: null,
  attempt_count: 1,
  last_attempt_at: "2026-09-03T09:07:00Z",
  last_reconciled_at: "2026-09-03T09:07:00Z",
  result_reference: "result-001",
};

const verification = {
  status: "verified_success",
  observed_resource_state: "refunded in simulator",
  verifier_source: "action-gateway-simulator",
  verification_version: "verification-v1",
  evidence_references: ["verification-001"],
  recorded_at: "2026-09-03T09:07:00Z",
  checksum: "verification-checksum",
};

const freshRun = {
  run_id: "run-001",
  tenant_id: "demo-tenant",
  case_id: "case-001",
  correlation_id: "fresh-correlation",
  execution_mode: "fresh_agent",
  provider_mode: "live",
  action_environment: "simulator",
  profile: "qualified-profile",
  provider: "qualified-provider",
  model: "qualified-model",
  status: "completed",
  analysis: {
    schema_version: "fresh-agent-analysis-v1.0.0",
    analysis_id: "analysis-001",
    tenant_id: "demo-tenant",
    case_id: "case-001",
    correlation_id: "fresh-correlation",
    uncertainty: "Payment ownership remains uncertain.",
    attributions: [],
    proposals: [],
    refusal_records: [],
  },
  proposal_validation: {},
  policy_result: null,
  error: null,
  provenance: {
    prompt_version: "prompt-v1",
    harness_version: "harness-v1",
    parser_version: "parser-v1",
    runtime_version: "runtime-v1",
    request_checksum: "request-checksum",
    response_checksum: "response-checksum",
    token_count: 12,
    estimated_cost: null,
    fresh_execution_observed: true,
    attempted_providers: [{ provider: "qualified-provider", model: "qualified-model" }],
  },
  remote_side_effects: [],
};

test("refreshes the detail from the authoritative read model after a fresh agent run", async ({ page }) => {
  let detailReads = 0;
  await page.route("**/tenants/demo-tenant/demo/mode**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(modePayload) }));
  await page.route("**/tenants/demo-tenant/cases/case-001/operator-view", (route) => {
    detailReads += 1;
    const view = detailReads === 1 ? baseView : { ...baseView, agent_analysis: persistedAgentAnalysis };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(view) });
  });
  await page.route("**/tenants/demo-tenant/cases/case-001/agent-runs", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(freshRun) }));

  await page.goto("/cases/case-001");
  await expect(page.getByRole("heading", { name: "case-001" })).toBeVisible();
  await page.getByRole("button", { name: "Run fresh agent" }).click();

  await expect.poll(() => detailReads).toBeGreaterThan(1);
  await expect(page.getByText("Payment ownership remains uncertain.", { exact: true })).toBeVisible();
  await expect(page.getByText("Authoritative analysis · completed", { exact: true })).toBeVisible();
});

test("refetches authoritative approval and simulator state after commands", async ({ page }) => {
  let detailReads = 0;
  await page.route("**/tenants/demo-tenant/demo/mode**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(modePayload) }));
  await page.route("**/tenants/demo-tenant/cases/case-001/operator-view", (route) => {
    detailReads += 1;
    const view = detailReads === 1
      ? { ...baseView, proposal, policy_decision: policyDecision, approval: pendingApproval }
      : detailReads === 2
        ? { ...baseView, proposal, policy_decision: policyDecision, approval: approvedApproval }
        : { ...baseView, proposal, policy_decision: policyDecision, approval: approvedApproval, action: actionLifecycle, verification };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(view) });
  });
  await page.route("**/tenants/demo-tenant/approvals/approve", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(approvedApproval) }));
  await page.route("**/tenants/demo-tenant/cases/case-001/actions/execute-approved", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(actionLifecycle) }));

  await page.goto("/cases/case-001");
  await expect(page.getByRole("heading", { name: "case-001" })).toBeVisible();
  await page.getByRole("button", { name: "Approve exact action" }).click();
  await expect.poll(() => detailReads).toBeGreaterThan(1);
  await expect(page.getByRole("region", { name: "Approval" }).getByText("approved", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Run approved action in simulator" }).click();
  await expect.poll(() => detailReads).toBeGreaterThan(2);
  await expect(page.getByText("reconciled", { exact: true })).toBeVisible();
  await expect(page.getByText("verified success", { exact: true })).toBeVisible();
});
