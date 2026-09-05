import { describe, expect, it, vi } from "vitest";
import {
  freshAgentRunSchema,
  getCase,
  getCaseInbox,
  getLatestAgentRun,
  askHelp,
  listCases,
  modeAvailabilitySchema,
  parseOperatorCaseView,
} from "./api";

const replayMode = {
  requested_mode: "replay" as const,
  effective_mode: "replay" as const,
  final_mode: "replay" as const,
  provider_available: false,
  connector_available: false,
  provider_qualified: false,
  connector_qualified: false,
  live_execution_occurred: false,
  live_actions_enabled: false,
  live_financial_actions_enabled: false,
  availability_reasons: ["replay was explicitly requested"],
  fallback_reason: null,
  label: "replay",
  simulation_notice: "REPLAY — simulation / no merchant actions",
  decision_version: "mode-selection-v1.0.0",
};

describe("typed operator API boundaries", () => {
  it("submits bounded documentation help through the authenticated help route", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          status: "answered",
          answer: "Use the verified webhook contract.",
          sources: [{ source_id: "intake.webhook-verification", title: "Webhook verification", path: "docs/integrations/razorpay-test-mode.md" }],
          model_profile: "reclaim-help-deepseek",
          model_revision: "test-model",
          request_id: "help:test",
        }),
      }),
    );

    const result = await askHelp("tenant-1", "How do I verify a webhook?");

    expect(result.status).toBe("answered");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining("/help/chat"),
      expect.objectContaining({ headers: expect.objectContaining({ "X-Tenant-ID": "tenant-1" }) }),
    );
    vi.unstubAllGlobals();
  });

  it("accepts server-qualified replay mode", () => {
    expect(modeAvailabilitySchema.parse(replayMode).final_mode).toBe("replay");
  });

  it("rejects a case view with a non-integer financial value", () => {
    const invalid = {
      case: { case_id: "case-1", tenant_id: "tenant-1", state: "analyzed" },
      timeline: [],
      exposure: {
        currency: "INR",
        gross_exposure_minor: 100.5,
        recoverable_value_minor: 100,
        contained_value_minor: 0,
        legitimate_value_disrupted_minor: 0,
        irreversible_loss_minor: 0,
        remaining_exposure_minor: 100,
        calculation_version: "exposure-v1.0.0",
      },
      audit: [],
      mode: replayMode,
    };
    expect(() => parseOperatorCaseView(invalid)).toThrow("schema validation");
  });

  it("accepts nullable metadata from the authoritative PostgreSQL read model", () => {
    const view = parseOperatorCaseView({
      case: {
        case_id: "case-1",
        tenant_id: "tenant-1",
        incident_id: null,
        merchant_name: null,
        state: "timeline_ready",
        owner_id: null,
        severity: null,
        last_refreshed_at: null,
      },
      timeline: [
        {
          event_id: "event-1",
          occurred_at: "2026-09-01T09:00:00Z",
          effective_at: null,
          observed_at: null,
          canonical_event_type: "profile.changed",
          resource: null,
          source_identity: null,
          attribution: null,
          evidence_references: [],
          provenance: { method: null, version: null, source: null, checksum: null },
          uncertainty_reasons: [],
          source_event_ids: [],
        },
      ],
      exposure: {
        currency: "INR",
        gross_exposure_minor: 0,
        recoverable_value_minor: 0,
        contained_value_minor: 0,
        legitimate_value_disrupted_minor: 0,
        irreversible_loss_minor: 0,
        remaining_exposure_minor: 0,
        calculation_version: "exposure-v1.0.0",
      },
      audit: [
        {
          audit_id: "audit-1",
          recorded_at: "2026-09-01T09:00:00Z",
          actor: "local-demo-seeder",
          action: "case.synthetic.seeded",
          outcome: "timeline_ready",
          narrative: null,
          input_references: [],
          output_references: [],
          evidence_references: [],
          policy_version_id: null,
          model_version: null,
          provider_version: null,
          approval_id: null,
          execution_id: null,
          correlation_ids: [],
          previous_record_checksum: null,
          record_checksum: "checksum-1",
        },
      ],
      mode: replayMode,
    });

    expect(view.case.case_id).toBe("case-1");
    expect(view.timeline[0]?.provenance.method).toBeNull();
    expect(view.audit[0]?.model_version).toBeNull();
  });

  it("keeps fresh-agent provenance and replay separation explicit", () => {
    const run = freshAgentRunSchema.parse({
      run_id: "agent-run:test",
      tenant_id: "tenant-1",
      case_id: "case-1",
      correlation_id: "corr-1",
      execution_mode: "fresh_agent",
      provider_mode: "live",
      action_environment: "simulator",
      profile: "reclaim-specialist",
      provider: "local",
      model: "specialist",
      status: "unavailable",
      analysis: null,
      proposal_validation: {},
      policy_result: null,
      error: "model provider unavailable",
      provenance: {
        prompt_version: "prompt-v1",
        harness_version: "harness-v1",
        parser_version: "parser-v1",
        runtime_version: "runtime-v1",
        request_checksum: "request-checksum",
        response_checksum: null,
        token_count: null,
        estimated_cost: null,
        fresh_execution_observed: true,
        attempted_providers: [{ profile: "reclaim-specialist", provider: "local", model: "specialist" }],
      },
      remote_side_effects: [],
    });
    expect(run.execution_mode).toBe("fresh_agent");
    expect(run.provider_mode).toBe("live");
    expect(run.provenance.fresh_execution_observed).toBe(true);
  });

  it("identifies a non-JSON proxy failure as API unavailability", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: vi.fn().mockRejectedValue(new Error("not JSON")),
      }),
    );

    await expect(getCaseInbox("tenant-1")).rejects.toMatchObject({
      kind: "availability",
      status: 500,
      message: "The authoritative API is unavailable. Verify the API service and deployment health check.",
    });

    vi.unstubAllGlobals();
  });

  it("parses the current cursor page and exact orchestration summary", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          schema_version: "1.0.0",
          tenant_id: "tenant-1",
          correlation_id: "corr-1",
          items: [
            {
              tenant_id: "tenant-1",
              case_id: "case-1",
              incident_id: "incident-1",
              merchant_name: "Merchant",
              source: "merchant_portal",
              incident_type: "account_takeover",
              occurred_at: "2026-09-03T09:00:00Z",
              state: "timeline_ready",
              updated_at: "2026-09-03T09:01:00Z",
              created_at: "2026-09-03T09:00:00Z",
              identifiers: {},
              reported_amount_minor: null,
              reported_currency: null,
              external_reference: null,
              orchestration: {
                run_id: "run-1",
                workflow_version: "incident-analysis-handoff.v1",
                external_execution_id: "execution-1",
                stage: "analyze",
                status: "requires_attention",
                queued_at: "2026-09-03T09:00:00Z",
                started_at: null,
                completed_at: null,
                updated_at: "2026-09-03T09:01:00Z",
                failure_code: "model_unavailable",
              },
            },
          ],
          next_cursor: "cursor-1",
          has_more: true,
          limit: 25,
        }),
      }),
    );

    const page = await listCases("tenant-1", { limit: 25 });

    expect(page.items[0]?.orchestration?.status).toBe("requires_attention");
    expect(page.next_cursor).toBe("cursor-1");
    expect(page.has_more).toBe(true);
    vi.unstubAllGlobals();
  });

  it("uses tenant-scoped authoritative detail and persisted agent-run paths", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: string) => ({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(
        input.endsWith("/operator-view")
          ? {
              case: {
                case_id: "case/1",
                tenant_id: "tenant/1",
                incident_id: null,
                merchant_name: null,
                state: "timeline_ready",
                owner_id: null,
                severity: null,
                last_refreshed_at: null,
              },
              timeline: [],
              exposure: {
                currency: "INR",
                gross_exposure_minor: 0,
                recoverable_value_minor: 0,
                contained_value_minor: 0,
                legitimate_value_disrupted_minor: 0,
                irreversible_loss_minor: 0,
                remaining_exposure_minor: 0,
                calculation_version: "exposure-v1.0.0",
              },
              audit: [],
              mode: replayMode,
              agent_analysis: {
                analysis_id: "analysis-1",
                run_id: "agent-run-1",
                status: "completed",
                mode: "live",
                provider: "local",
                model: "specialist",
                uncertainty: ["review required"],
                attributions: [],
                refusal_records: [],
                provenance: {
                  authoritative_store: "postgresql",
                  request_checksum: "request-checksum",
                  response_checksum: "response-checksum",
                  deterministic_analysis_checksum: "analysis-checksum",
                  deterministic_exposure_checksum: "exposure-checksum",
                },
              },
            }
          : {
              run_id: "agent-run-1",
              tenant_id: "tenant/1",
              case_id: "case/1",
              correlation_id: "corr-1",
              execution_mode: "fresh_agent",
              provider_mode: "live",
              action_environment: "simulator",
              profile: "reclaim-specialist",
              provider: "local",
              model: "specialist",
              status: "completed",
              analysis: null,
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
                token_count: 1,
                estimated_cost: null,
                fresh_execution_observed: true,
                attempted_providers: [],
              },
              remote_side_effects: [],
            },
      ),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const view = await getCase("tenant/1", "case/1");
    const run = await getLatestAgentRun("tenant/1", "case/1", "agent-run-1");

    expect(view.agent_analysis?.run_id).toBe("agent-run-1");
    expect(run.run_id).toBe("agent-run-1");
    expect(fetchMock.mock.calls[0]?.[0]).toContain("/tenants/tenant%2F1/cases/case%2F1/operator-view");
    expect(fetchMock.mock.calls[1]?.[0]).toContain("/tenants/tenant%2F1/cases/case%2F1/agent-runs/agent-run-1");
    vi.unstubAllGlobals();
  });

  it("rejects an untyped persisted agent-analysis payload", () => {
    expect(() =>
      parseOperatorCaseView({
        case: { case_id: "case-1", tenant_id: "tenant-1", state: "timeline_ready" },
        timeline: [],
        exposure: {
          currency: "INR",
          gross_exposure_minor: 0,
          recoverable_value_minor: 0,
          contained_value_minor: 0,
          legitimate_value_disrupted_minor: 0,
          irreversible_loss_minor: 0,
          remaining_exposure_minor: 0,
          calculation_version: "exposure-v1.0.0",
        },
        audit: [],
        mode: replayMode,
        agent_analysis: { analysis_id: "" },
      }),
    ).toThrow("schema validation");
  });
});
