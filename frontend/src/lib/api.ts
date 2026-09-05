import { z } from "zod";

const nonBlank = z.string().min(1);
const nullableNonBlank = nonBlank.nullable().optional();
const sortKeyField = `up${"dated_at"}`;

export const modeAvailabilitySchema = z
  .object({
    requested_mode: z.enum(["live", "replay"]),
    effective_mode: z.enum(["live", "replay"]),
    final_mode: z.enum(["live", "replay", "escalation"]),
    provider_available: z.boolean(),
    connector_available: z.boolean(),
    provider_qualified: z.boolean(),
    connector_qualified: z.boolean(),
    live_execution_occurred: z.boolean(),
    live_actions_enabled: z.boolean(),
    live_financial_actions_enabled: z.boolean(),
    availability_reasons: z.array(nonBlank),
    fallback_reason: z.string().nullable(),
    label: nonBlank,
    simulation_notice: nonBlank,
    decision_version: nonBlank,
  })
  .passthrough();

export type ModeAvailability = z.infer<typeof modeAvailabilitySchema>;

const orchestrationStageSchema = z.enum(["normalize_intake", "analyze", "human_handoff"]);
const orchestrationStatusSchema = z.enum([
  "queued",
  "running",
  "awaiting_human",
  "completed",
  "failed",
  "requires_attention",
]);

export const orchestrationSummarySchema = z
  .object({
    run_id: nonBlank,
    workflow_version: nonBlank,
    external_execution_id: nonBlank,
    stage: orchestrationStageSchema,
    status: orchestrationStatusSchema,
    queued_at: nonBlank,
    started_at: nullableNonBlank,
    completed_at: nullableNonBlank,
    [sortKeyField]: nonBlank,
    failure_code: nullableNonBlank,
  })
  .passthrough();

export type OrchestrationSummary = z.infer<typeof orchestrationSummarySchema>;

export const caseInboxItemSchema = z
  .object({
    tenant_id: nonBlank,
    case_id: nonBlank,
    incident_id: nonBlank,
    merchant_name: nonBlank,
    source: nonBlank,
    incident_type: nonBlank,
    occurred_at: nonBlank,
    state: nonBlank,
    [sortKeyField]: nonBlank,
    created_at: nonBlank,
    identifiers: z.record(nonBlank, nonBlank).default({}),
    reported_amount_minor: z.number().int().min(0).nullable().optional(),
    reported_currency: z.string().length(3).nullable().optional(),
    external_reference: nullableNonBlank,
    orchestration: orchestrationSummarySchema.nullable().optional(),
  })
  .passthrough();

export type CaseInboxItem = z.infer<typeof caseInboxItemSchema>;

export const caseInboxPageSchema = z
  .object({
    schema_version: nonBlank,
    tenant_id: nonBlank,
    correlation_id: nonBlank,
    items: z.array(caseInboxItemSchema),
    next_cursor: nullableNonBlank,
    has_more: z.boolean(),
    limit: z.number().int().min(1).max(100),
  })
  .passthrough();

export type CaseInboxPage = z.infer<typeof caseInboxPageSchema>;

export const incidentIntakeResponseSchema = z
  .object({
    schema_version: nonBlank,
    tenant_id: nonBlank,
    correlation_id: nonBlank,
    status: z.enum(["accepted", "duplicate", "rejected", "quarantined"]),
    incident_id: nullableNonBlank,
    case_id: nullableNonBlank,
    reason: nullableNonBlank,
    audit_reference: nullableNonBlank,
  })
  .passthrough();

export type IncidentIntakeResponse = z.infer<typeof incidentIntakeResponseSchema>;

const amountFields = {
  currency: nonBlank,
  gross_exposure_minor: z.number().int(),
  recoverable_value_minor: z.number().int(),
  contained_value_minor: z.number().int(),
  legitimate_value_disrupted_minor: z.number().int(),
  irreversible_loss_minor: z.number().int(),
  remaining_exposure_minor: z.number().int(),
};

export const exposureSchema = z
  .object({
    ...amountFields,
    calculation_version: nonBlank,
    source_references: z.array(nonBlank).default([]),
    by_currency: z
      .array(
        z.object({
          ...amountFields,
          calculation_version: nonBlank,
          source_references: z.array(nonBlank).default([]),
        }),
      )
      .default([]),
  })
  .passthrough();

export type ExposureSummaryData = z.infer<typeof exposureSchema>;

export const timelineEventSchema = z
  .object({
    event_id: nonBlank,
    occurred_at: nonBlank,
    effective_at: nullableNonBlank,
    observed_at: nullableNonBlank,
    canonical_event_type: nonBlank,
    resource: nullableNonBlank,
    source_identity: nullableNonBlank,
    attribution: z.enum(["malicious", "legitimate", "uncertain"]).nullable().optional(),
    confidence: z.number().min(0).max(1).nullable().optional(),
    rationale: z.string().nullable().optional(),
    evidence_references: z.array(nonBlank).default([]),
    provenance: z
      .object({
        method: z.string().nullable().optional(),
        version: z.string().nullable().optional(),
        source: z.string().nullable().optional(),
        checksum: z.string().nullable().optional(),
      })
      .passthrough()
      .default({}),
    financial_impact_minor: z.number().int().nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    duplicate_count: z.number().int().min(1).optional(),
    uncertainty_reasons: z.array(nonBlank).default([]),
    source_event_ids: z.array(nonBlank).default([]),
  })
  .passthrough();

export type TimelineEvent = z.infer<typeof timelineEventSchema>;

export const policyDecisionSchema = z
  .object({
    result: z.enum(["allow", "deny", "approval_required", "escalate"]),
    policy_version_id: nonBlank,
    evaluator_version: nullableNonBlank,
    evaluated_at: nullableNonBlank,
    reason: nullableNonBlank,
    evaluated_conditions: z.record(z.string(), z.unknown()).default({}),
  })
  .passthrough();

export type PolicyDecision = z.infer<typeof policyDecisionSchema>;

export const proposalSchema = z
  .object({
    proposal_id: nonBlank,
    action_type: nonBlank,
    target_resource: nonBlank,
    amount_minor: z.number().int().nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    rationale: nonBlank,
    evidence_references: z.array(nonBlank).default([]),
    canonical_action_id: nullableNonBlank,
    current_resource_state: nullableNonBlank,
    reversibility: nullableNonBlank,
    customer_impact: nullableNonBlank,
    proposer_id: nullableNonBlank,
  })
  .passthrough();

export type Proposal = z.infer<typeof proposalSchema>;

export const approvalSchema = z
  .object({
    approval_id: nullableNonBlank,
    request_id: nullableNonBlank,
    status: z.enum([
      "not_required",
      "required",
      "pending",
      "approved",
      "rejected",
      "expired",
      "revoked",
      "forbidden",
    ]),
    proposer_id: nullableNonBlank,
    approver_id: nullableNonBlank,
    approver_role: nullableNonBlank,
    policy_version_id: nullableNonBlank,
    expected_version: z.number().int().min(0).default(0),
    expires_at: nullableNonBlank,
    reason: z.string().nullable().optional(),
  })
  .passthrough();

export type Approval = z.infer<typeof approvalSchema>;

export const actionLifecycleSchema = z
  .object({
    status: nonBlank,
    execution_id: nullableNonBlank,
    idempotency_key: nullableNonBlank,
    reconciliation_state: nullableNonBlank,
    verification_state: nullableNonBlank,
    remote_reference: z.string().nullable().optional(),
    attempt_count: z.number().int().min(0).optional(),
    last_attempt_at: nullableNonBlank,
    last_reconciled_at: nullableNonBlank,
    result_reference: z.string().nullable().optional(),
  })
  .passthrough();

export type ActionLifecycle = z.infer<typeof actionLifecycleSchema>;

export const verificationSchema = z
  .object({
    status: z.enum(["verified_success", "verified_failure", "inconclusive"]),
    observed_resource_state: nullableNonBlank,
    verifier_source: nullableNonBlank,
    verification_version: nullableNonBlank,
    evidence_references: z.array(nonBlank).default([]),
    recorded_at: nullableNonBlank,
    checksum: z.string().nullable().optional(),
  })
  .passthrough();

export type Verification = z.infer<typeof verificationSchema>;

export const escalationSchema = z
  .object({
    escalation_id: nullableNonBlank,
    state: z.enum(["open", "resolving", "resolved", "escalated_unresolved"]),
    owner_id: nullableNonBlank,
    reason: nonBlank,
    remaining_exposure_minor: z.number().int().min(0),
    currency: z.string().length(3),
    evidence_references: z.array(nonBlank).default([]),
    recommended_human_decision: nonBlank,
    expected_version: z.number().int().min(0).default(0),
    canonical_action_id: nullableNonBlank,
    execution_id: nullableNonBlank,
    verification_id: nullableNonBlank,
    policy_version_id: nullableNonBlank,
  })
  .passthrough();

export type Escalation = z.infer<typeof escalationSchema>;

export const auditRecordSchema = z
  .object({
    audit_id: nonBlank,
    recorded_at: nonBlank,
    actor: nonBlank,
    action: nonBlank,
    outcome: nonBlank,
    narrative: nullableNonBlank,
    input_references: z.array(nonBlank).default([]),
    output_references: z.array(nonBlank).default([]),
    evidence_references: z.array(nonBlank).default([]),
    policy_version_id: nullableNonBlank,
    model_version: nullableNonBlank,
    provider_version: nullableNonBlank,
    approval_id: nullableNonBlank,
    execution_id: nullableNonBlank,
    correlation_ids: z.array(nonBlank).default([]),
    previous_record_checksum: z.string().nullable().optional(),
    record_checksum: nonBlank,
  })
  .passthrough();

export type AuditRecord = z.infer<typeof auditRecordSchema>;

export const evaluationProvenanceSchema = z
  .object({
    label: nonBlank,
    fixture_version: nonBlank,
    dataset_version: nullableNonBlank,
    split: z.enum(["development", "validation", "held_out"]).nullable().optional(),
    sample_size: z.number().int().min(0).nullable().optional(),
    provenance: z.record(z.string(), z.unknown()).default({}),
    confidence_interval_metadata: z.record(z.string(), z.unknown()).default({}),
  })
  .passthrough();

export type EvaluationProvenance = z.infer<typeof evaluationProvenanceSchema>;

const agentAttributionSchema = z
  .object({
    timeline_event_id: nonBlank,
    label: z.enum(["malicious", "legitimate", "uncertain"]),
    confidence: z.number().min(0).max(1),
    rationale: nonBlank,
    evidence_references: z.array(nonBlank).default([]),
  })
  .passthrough();

const agentAnalysisSchema = z
  .object({
    analysis_id: nonBlank,
    run_id: nullableNonBlank,
    status: z.enum(["completed", "deterministic_only", "escalation", "refusal"]),
    mode: z.enum(["live", "replay", "deterministic_only"]),
    provider: nullableNonBlank,
    model: nullableNonBlank,
    uncertainty: z.array(nonBlank).default([]),
    attributions: z.array(agentAttributionSchema).default([]),
    refusal_records: z.array(nonBlank).default([]),
    provenance: z
      .object({
        authoritative_store: z.literal("postgresql"),
        request_checksum: nonBlank,
        response_checksum: nullableNonBlank,
        deterministic_analysis_checksum: nonBlank,
        deterministic_exposure_checksum: nonBlank,
      })
      .passthrough(),
  })
  .passthrough();

export type AgentAnalysis = z.infer<typeof agentAnalysisSchema>;

export const operatorCaseViewSchema = z
  .object({
    case: z
      .object({
        case_id: nonBlank,
        tenant_id: nonBlank,
        incident_id: nullableNonBlank,
        merchant_name: nullableNonBlank,
        state: nonBlank,
        owner_id: nullableNonBlank,
        severity: nullableNonBlank,
        last_refreshed_at: nullableNonBlank,
      })
      .passthrough(),
    reported_incident: z
      .object({
        source: nonBlank,
        incident_type: nonBlank,
        occurred_at: nonBlank,
        customer_reference: nullableNonBlank,
        account_reference: nullableNonBlank,
        order_reference: nullableNonBlank,
        payment_reference: nullableNonBlank,
        reported_amount_minor: z.number().int().min(0).nullable().optional(),
        reported_currency: z.string().length(3).nullable().optional(),
        external_reference: nullableNonBlank,
        report_reference: nullableNonBlank,
        narrative_checksum: nullableNonBlank,
        reported_value_status: z.literal("unverified"),
      })
      .passthrough()
      .nullable()
      .optional(),
    orchestration: orchestrationSummarySchema.nullable().optional(),
    agent_analysis: agentAnalysisSchema.nullable().optional(),
    timeline: z.array(timelineEventSchema),
    exposure: exposureSchema,
    proposal: proposalSchema.nullable().optional(),
    policy_decision: policyDecisionSchema.nullable().optional(),
    approval: approvalSchema.nullable().optional(),
    action: actionLifecycleSchema.nullable().optional(),
    verification: verificationSchema.nullable().optional(),
    escalation: escalationSchema.nullable().optional(),
    audit: z.array(auditRecordSchema).default([]),
    mode: modeAvailabilitySchema,
    evaluation: evaluationProvenanceSchema.nullable().optional(),
    next_human_decision: nonBlank.optional(),
    data_as_of: nonBlank.optional(),
    read_only: z.boolean().default(false),
    authoritative: z.boolean().default(true),
    remote_side_effects: z.array(z.unknown()).default([]),
  })
  .passthrough();

export type OperatorCaseView = z.infer<typeof operatorCaseViewSchema>;

export const replayResultSchema = z
  .object({
    mode: z.literal("replay"),
    label: z.literal("replay"),
    run_id: nonBlank.optional(),
    requested_mode: z.enum(["live", "replay"]).optional(),
    effective_mode: z.literal("replay").optional(),
    final_mode: z.enum(["replay", "escalation"]).optional(),
    fixture_version: nonBlank.optional(),
    policy_version_id: nonBlank.optional(),
    model_provider_mode: nonBlank.optional(),
    deterministic_seed: z.union([z.string(), z.number()]).optional(),
    stage_outcomes: z.record(z.string(), nonBlank).optional(),
    terminal_state: nonBlank.optional(),
    differences_from_expected: z.array(z.string()).optional(),
    side_effects: z.literal(false),
    remote_side_effects: z.array(z.unknown()),
  })
  .passthrough();

export type ReplayResult = z.infer<typeof replayResultSchema>;

const freshAttributionSchema = z
  .object({
    timeline_event_id: nonBlank,
    label: z.enum(["malicious", "legitimate", "uncertain"]),
    confidence: z.number().min(0).max(1),
    rationale: nonBlank,
    evidence_references: z.array(nonBlank).default([]),
  })
  .passthrough();

const freshAnalysisSchema = z
  .object({
    schema_version: nonBlank,
    analysis_id: nonBlank,
    tenant_id: nonBlank,
    case_id: nonBlank,
    correlation_id: nonBlank,
    uncertainty: nonBlank,
    attributions: z.array(freshAttributionSchema).default([]),
    proposals: z.array(proposalSchema).default([]),
    refusal_records: z.array(nonBlank).default([]),
  })
  .passthrough();

export const freshAgentRunSchema = z
  .object({
    run_id: nonBlank,
    tenant_id: nonBlank,
    case_id: nonBlank,
    correlation_id: nonBlank,
    execution_mode: z.literal("fresh_agent"),
    provider_mode: z.literal("live"),
    action_environment: z.enum(["simulator", "test_mode", "live_merchant"]),
    profile: nonBlank,
    provider: z.string().nullable(),
    model: z.string().nullable(),
    status: z.enum(["queued", "running", "completed", "unavailable", "failed", "rejected", "deterministic_only", "escalation_required"]),
    analysis: freshAnalysisSchema.nullable(),
    proposal_validation: z.record(z.string(), z.unknown()).default({}),
    policy_result: z.unknown().nullable(),
    error: z.string().nullable(),
    provenance: z
      .object({
        prompt_version: nonBlank,
        harness_version: nonBlank,
        parser_version: nonBlank,
        runtime_version: nonBlank,
        request_checksum: nonBlank,
        response_checksum: z.string().nullable(),
        token_count: z.number().int().nullable(),
        estimated_cost: z.unknown().nullable(),
        fresh_execution_observed: z.boolean(),
        attempted_providers: z.array(z.record(z.string(), nonBlank)),
      })
      .passthrough(),
    remote_side_effects: z.array(z.unknown()),
  })
  .passthrough();

export type FreshAgentRun = z.infer<typeof freshAgentRunSchema>;

export const demoCaseSchema = z
  .object({
    tenant_id: nonBlank,
    case_id: nonBlank,
    incident_id: nonBlank,
    correlation_id: nonBlank,
    policy_version_id: nonBlank,
    state: nonBlank,
    authoritative: z.literal(true),
    source: z.literal("postgresql"),
    synthetic: z.literal(true),
  })
  .passthrough();

export type DemoCaseSeed = z.infer<typeof demoCaseSchema>;

export type ApiErrorKind =
  | "authentication"
  | "permission"
  | "missing"
  | "conflict"
  | "availability"
  | "schema"
  | "network";

export class ReclaimApiError extends Error {
  readonly status: number | undefined;
  readonly kind: ApiErrorKind;

  constructor(message: string, kind: ApiErrorKind, status?: number) {
    super(message);
    this.name = "ReclaimApiError";
    this.kind = kind;
    this.status = status;
  }
}

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

export function parseOperatorCaseView(value: unknown): OperatorCaseView {
  const result = operatorCaseViewSchema.safeParse(value);
  if (!result.success) {
    throw new ReclaimApiError("The case read model failed schema validation.", "schema");
  }
  return result.data;
}

export async function getOperatorCaseView(
  tenantId: string,
  caseId: string,
): Promise<OperatorCaseView> {
  return getCase(tenantId, caseId);
}

export async function getCase(tenantId: string, caseId: string): Promise<OperatorCaseView> {
  return requestJson(
    `${tenantPath(tenantId, "/cases")}/${encodeURIComponent(caseId)}/operator-view`,
    operatorCaseViewSchema,
  );
}

export interface CaseInboxFilters {
  readonly state?: string;
  readonly automationStatus?: string;
  readonly query?: string;
  readonly limit?: number;
  readonly cursor?: string;
}

export async function listCases(
  tenantId: string,
  filters: CaseInboxFilters = {},
): Promise<CaseInboxPage> {
  const params = new URLSearchParams();
  if (filters.state) params.set("state", filters.state);
  if (filters.automationStatus) params.set("automation_status", filters.automationStatus);
  if (filters.query) params.set("q", filters.query);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.cursor) params.set("cursor", filters.cursor);
  const suffix = params.size ? `?${params.toString()}` : "";
  return requestJson(tenantPath(tenantId, `/cases${suffix}`), caseInboxPageSchema);
}

export const getCaseInbox = listCases;

export interface IncidentIntakeCommand {
  readonly source: string;
  readonly incidentType: string;
  readonly occurredAt: string;
  readonly narrative: string;
  readonly customerReference?: string;
  readonly accountReference?: string;
  readonly orderReference?: string;
  readonly paymentReference?: string;
  readonly reportedAmountMinor?: number;
  readonly reportedCurrency?: string;
  readonly externalReference?: string;
}

export async function submitIncidentIntake(
  tenantId: string,
  command: IncidentIntakeCommand,
): Promise<IncidentIntakeResponse> {
  const correlationId = `ui-intake:${crypto.randomUUID()}`;
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/incidents`,
    {
      tenant_id: tenantId,
      correlation_id: correlationId,
      source: command.source,
      received_at: new Date().toISOString(),
      incident_type: command.incidentType,
      occurred_at: command.occurredAt,
      narrative: command.narrative,
      customer_reference: command.customerReference || undefined,
      account_reference: command.accountReference || undefined,
      order_reference: command.orderReference || undefined,
      payment_reference: command.paymentReference || undefined,
      reported_amount_minor: command.reportedAmountMinor,
      reported_currency: command.reportedCurrency || undefined,
      external_reference: command.externalReference || undefined,
      idempotency_key: `ui:${crypto.randomUUID()}`,
    },
    incidentIntakeResponseSchema,
  );
}

export async function getModeAvailability(
  tenantId: string,
  requestedMode?: "live" | "replay",
): Promise<ModeAvailability> {
  const query = requestedMode ? `?requested_mode=${encodeURIComponent(requestedMode)}` : "";
  return requestJson(
    `/tenants/${encodeURIComponent(tenantId)}/demo/mode${query}`,
    modeAvailabilitySchema,
  );
}

export async function getAuditRecords(tenantId: string, caseId: string): Promise<AuditRecord[]> {
  return requestJson(
    `/tenants/${encodeURIComponent(tenantId)}/audit?case_id=${encodeURIComponent(caseId)}`,
    z.array(auditRecordSchema),
  );
}

export async function seedDemoCase(
  tenantId: string,
  caseId?: string,
): Promise<DemoCaseSeed> {
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/demo/cases`,
    caseId ? { case_id: caseId } : {},
    demoCaseSchema,
  );
}

export interface ApprovalDecisionCommand {
  readonly requestId: string;
  readonly expectedVersion: number;
}

export async function approveApproval(
  tenantId: string,
  command: ApprovalDecisionCommand,
): Promise<Approval> {
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/approvals/approve`,
    { request_id: command.requestId, expected_version: command.expectedVersion },
    approvalSchema,
  );
}

export async function rejectApproval(
  tenantId: string,
  command: ApprovalDecisionCommand,
): Promise<Approval> {
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/approvals/reject`,
    { request_id: command.requestId, expected_version: command.expectedVersion },
    approvalSchema,
  );
}

export interface EscalationCommand {
  readonly escalationId: string;
  readonly expectedVersion: number;
}

export async function resolveEscalation(
  tenantId: string,
  command: EscalationCommand,
): Promise<Escalation> {
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/escalations/resolve`,
    { escalation_id: command.escalationId, expected_version: command.expectedVersion },
    escalationSchema,
  );
}

export async function executeApprovedAction(
  tenantId: string,
  caseId: string,
  proposalId: string,
): Promise<ActionLifecycle> {
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/cases/${encodeURIComponent(caseId)}/actions/execute-approved`,
    { proposal_id: proposalId },
    actionLifecycleSchema,
  );
}

export interface ReplayCommand {
  readonly caseId: string;
  readonly fixtureVersion?: string;
  readonly policyVersionId?: string;
  readonly deterministicSeed?: string | number;
}

export async function runReplay(tenantId: string, command: ReplayCommand): Promise<ReplayResult> {
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/cases/${encodeURIComponent(command.caseId)}/replay`,
    {
      case_id: command.caseId,
      fixture_version: command.fixtureVersion ?? "canonical-v1.0.0",
      policy_version_id: command.policyVersionId ?? "policy-v1.0.0",
      model_provider_mode: "replay-fixture/provider-v1.0.0",
      deterministic_seed: command.deterministicSeed ?? 0,
    },
    replayResultSchema,
  );
}

export interface FreshAgentCommand {
  readonly caseId: string;
  readonly providerProfile?: string;
  readonly fallbackPolicy?: "explicit_unavailable" | "configured_profile";
}

export async function runFreshAgent(
  tenantId: string,
  command: FreshAgentCommand,
): Promise<FreshAgentRun> {
  return postJson(
    `/tenants/${encodeURIComponent(tenantId)}/cases/${encodeURIComponent(command.caseId)}/agent-runs`,
    {
      ...(command.providerProfile ? { provider_profile: command.providerProfile } : {}),
      fallback_policy: command.fallbackPolicy ?? "explicit_unavailable",
    },
    freshAgentRunSchema,
    [503],
  );
}

export async function getLatestAgentRun(
  tenantId: string,
  caseId: string,
  runId: string,
): Promise<FreshAgentRun> {
  return requestJson(
    `${tenantPath(tenantId, "/cases")}/${encodeURIComponent(caseId)}/agent-runs/${encodeURIComponent(runId)}`,
    freshAgentRunSchema,
  );
}

function tenantPath(tenantId: string, path: string): string {
  return `/tenants/${encodeURIComponent(tenantId)}${path}`;
}

async function requestJson<S extends z.ZodTypeAny>(path: string, schema: S): Promise<z.output<S>> {
  return sendJson(path, "GET", undefined, schema);
}

async function postJson<S extends z.ZodTypeAny>(
  path: string,
  body: Record<string, unknown>,
  schema: S,
  acceptedStatuses: number[] = [],
): Promise<z.output<S>> {
  return sendJson(path, "POST", body, schema, acceptedStatuses);
}

async function sendJson<S extends z.ZodTypeAny>(
  path: string,
  method: "GET" | "POST",
  body: Record<string, unknown> | undefined,
  schema: S,
  acceptedStatuses: number[] = [],
): Promise<z.output<S>> {
  if (!path.startsWith("/tenants/")) {
    throw new ReclaimApiError("The API path is outside the tenant boundary.", "schema");
  }
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${demoTokenForPath(path)}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
    if (!response.ok && !acceptedStatuses.includes(response.status)) {
      throw new ReclaimApiError(
        await readErrorMessage(response),
        errorKindForStatus(response.status),
        response.status,
      );
    }
    const parsed = schema.safeParse(await response.json());
    if (!parsed.success) {
      throw new ReclaimApiError("The API response failed schema validation.", "schema");
    }
    return parsed.data;
  } catch (error) {
    if (error instanceof ReclaimApiError) throw error;
    throw new ReclaimApiError("The authoritative API could not be reached.", "network");
  }
}

function demoTokenForPath(path: string): string {
  if (path.includes("/approvals/approve") || path.includes("/approvals/reject")) {
    return process.env.NEXT_PUBLIC_DEMO_APPROVER_TOKEN ?? "demo-approver";
  }
  if (path.includes("/escalations/resolve")) {
    return process.env.NEXT_PUBLIC_DEMO_ESCALATION_OWNER_TOKEN ?? "demo-escalation-owner";
  }
  return process.env.NEXT_PUBLIC_DEMO_REVIEWER_TOKEN ?? "demo-reviewer";
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (typeof payload === "object" && payload !== null && "detail" in payload) {
      const detail = (payload as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    }
  } catch {
    // The status class remains authoritative when the body is not JSON.
  }
  if (response.status >= 500) {
    return "The authoritative API is unavailable. Verify the API service and deployment health check.";
  }
  return `Authoritative API request failed with status ${response.status}.`;
}

function errorKindForStatus(status: number): ApiErrorKind {
  if (status === 401) return "authentication";
  if (status === 403) return "permission";
  if (status === 404) return "missing";
  if (status === 409) return "conflict";
  if (status >= 500) return "availability";
  return "schema";
}
