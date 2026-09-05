# Case Inbox API Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the redesigned `/cases` operator experience consume the current tenant-scoped PostgreSQL read models and typed command APIs, with authoritative refreshes after intake and every mutation.

**Architecture:** Keep the existing FastAPI route names and same-origin Next.js rewrite. Tighten the frontend gateway around the actual response contracts, extend the existing authoritative local case read model with persisted typed agent-analysis provenance, and make React state refetch after backend commands instead of manufacturing business state. Replay remains a separate fixture path and is never used as an API-failure fallback.

**Tech Stack:** FastAPI, Pydantic contracts, PostgreSQL repositories, Next.js 16, React 19, TypeScript, Zod, Vitest, Playwright, pytest.

**Spec:** `specs/001-incident-intake-containment/spec.md` plus the approved Case Inbox API synchronization request in the task conversation.

## Global Constraints

- PostgreSQL is authoritative for business state; n8n owns durable orchestration for new work; Redis is coordination only.
- The agent produces typed proposals only and never directly executes payments, refunds, cancellations, account mutations, database writes, shell commands, or arbitrary network calls.
- Financial values remain integer minor currency units with explicit currency.
- Replay is explicitly labeled and cannot be presented as live merchant state.
- Preserve unrelated dirty/untracked paths, especially `packages/contracts/action_gateway.py`, migrations `011/012`, `security-audits/`, `AGENTS.md`, and constitution/ADR files.
- Do not start T153 or T154, remove Temporal, train models, deploy, redesign the UI, or add realtime infrastructure.
- Do not claim live browser validation unless the API/Compose environment is actually available.

## Current Route Map Used by the UI

| Method | Path | Request | Response | Authority |
|---|---|---|---|---|
| GET | `/tenants/{tenant_id}/cases` | `state`, `automation_status`, `q`, `limit`, `cursor` query parameters | `CaseInboxPage` | `CaseInboxRepository` over PostgreSQL `cases`, `incidents`, `tenants`, latest `orchestration_runs` |
| GET | `/tenants/{tenant_id}/cases/{case_id}/operator-view` | tenant/case path plus reviewer bearer token | authoritative local operator read model | `LocalDemoRuntime.operator_view`, PostgreSQL repositories |
| POST | `/tenants/{tenant_id}/incidents` | `IncidentIntakeRequest` | `IncidentIntakeResponse` | PostgreSQL incident/case rows, MinIO evidence, outbox, audit |
| GET | `/tenants/{tenant_id}/demo/mode` | optional `requested_mode` | server-qualified mode payload | runtime configuration/provider availability |
| POST | `/tenants/{tenant_id}/cases/{case_id}/agent-runs` | `AgentRunRequest` | typed `FreshAgentRun` | fresh-agent runtime plus persisted model-analysis audit |
| GET | `/tenants/{tenant_id}/cases/{case_id}/agent-runs/{run_id}` | tenant/case/run path | typed persisted fresh run | PostgreSQL model-analysis audit when configured |
| POST | `/tenants/{tenant_id}/approvals/approve` | `request_id`, `expected_version` | approval record | approval service and PostgreSQL persistence callback |
| POST | `/tenants/{tenant_id}/approvals/reject` | `request_id`, `expected_version` | approval record | approval service and PostgreSQL persistence callback |
| POST | `/tenants/{tenant_id}/cases/{case_id}/actions/execute-approved` | `proposal_id`, optional simulator `scenario` | action lifecycle | Action Gateway simulator, PostgreSQL action/verification/escalation state |
| POST | `/tenants/{tenant_id}/escalations/resolve` | `escalation_id`, `expected_version` | escalation record | PostgreSQL escalation repository |
| GET | `/tenants/{tenant_id}/audit?case_id=...` | optional case scope | audit records | audit repository; embedded case-detail audit is the mounted local read path |
| POST/GET | `/tenants/{tenant_id}/cases/{case_id}/orchestration/...` | typed n8n start/claim/stage/recovery bodies | orchestration responses | PostgreSQL orchestration runs; n8n is the workflow caller |

### Task 1: Align the typed frontend gateway with authoritative contracts

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces `listCases(tenantId, filters): Promise<CaseInboxPage>` with `getCaseInbox` retained as a compatibility alias until component migration is complete.
- Produces `getCase(tenantId, caseId): Promise<OperatorCaseView>` for the mounted `/operator-view` read model.
- Produces `getLatestAgentRun(tenantId, caseId, runId): Promise<FreshAgentRun>` for an explicitly known persisted run.
- Preserves `submitIncidentIntake`, `runFreshAgent`, `approveApproval`, `rejectApproval`, `executeApprovedAction`, `resolveEscalation`, `getAuditRecords`, and `runReplay` route behavior.

- [ ] **Step 1: Write the failing gateway tests.** Add tests that stub `fetch` and assert `listCases` parses the real `CaseInboxPage` shape including `schema_version`, `tenant_id`, `correlation_id`, cursor metadata, nullable reported amount, and the exact six orchestration statuses. Add a detail test that parses `agent_analysis` with persisted run/provenance fields, and a request test that verifies the case-detail and agent-run paths are tenant-encoded.

```typescript
it("parses the current cursor page and exact orchestration summary", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue({
      schema_version: "1.0.0",
      tenant_id: "tenant-1",
      correlation_id: "corr-1",
      items: [{
        tenant_id: "tenant-1", case_id: "case-1", incident_id: "incident-1",
        merchant_name: "Merchant", source: "merchant_portal",
        incident_type: "account_takeover", occurred_at: "2026-09-03T09:00:00Z",
        state: "timeline_ready", updated_at: "2026-09-03T09:01:00Z",
        created_at: "2026-09-03T09:00:00Z", identifiers: {},
        reported_amount_minor: null, reported_currency: null, external_reference: null,
        orchestration: {
          run_id: "run-1", workflow_version: "incident-analysis-handoff.v1",
          external_execution_id: "execution-1", stage: "analyze", status: "requires_attention",
          queued_at: "2026-09-03T09:00:00Z", started_at: null,
          completed_at: null, updated_at: "2026-09-03T09:01:00Z", failure_code: "model_unavailable",
        },
      }],
      next_cursor: "cursor-1", has_more: true, limit: 25,
    }),
  }));

  const page = await listCases("tenant-1", { limit: 25 });
  expect(page.items[0]?.orchestration?.status).toBe("requires_attention");
  expect(page.next_cursor).toBe("cursor-1");
  vi.unstubAllGlobals();
});
```

- [ ] **Step 2: Run the new tests and verify the intended failure.**

Run: `npm test -- --run frontend/src/lib/api.test.ts` from `frontend/`

Expected: FAIL because `listCases`, `getCase`, `getLatestAgentRun`, or the `agent_analysis` schema does not yet exist.

- [ ] **Step 3: Implement the smallest gateway/schema change.** Centralize the response schemas and tenant path construction; remove the deliberately obfuscated `sortKeyField`; accept only backend-defined values; keep `passthrough` only where the current backend intentionally carries versioned extension metadata. Add `getCase` and `getLatestAgentRun`, then export `getCaseInbox = listCases` for existing callers.

```typescript
export async function listCases(tenantId: string, filters: CaseInboxFilters = {}): Promise<CaseInboxPage> {
  return requestJson(tenantPath(tenantId, "/cases", filters), caseInboxPageSchema);
}

export async function getCase(tenantId: string, caseId: string): Promise<OperatorCaseView> {
  return requestJson(`${tenantPath(tenantId, "/cases")}/${encodeURIComponent(caseId)}/operator-view`, operatorCaseViewSchema);
}

export const getCaseInbox = listCases;
```

- [ ] **Step 4: Run the gateway tests and frontend typecheck.**

Run: `npm test -- --run frontend/src/lib/api.test.ts` and `npm run typecheck` from `frontend/`

Expected: all API tests pass and TypeScript reports no errors.

### Task 2: Expose persisted fresh-agent analysis through the authoritative case read model

**Files:**
- Modify: `backend/app/local_runtime.py`
- Modify: `frontend/src/lib/api.ts`
- Test: `tests/acceptance/test_runtime_product.py` or a focused new test under `tests/unit/`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces an optional `agent_analysis` object in the authoritative `/operator-view` response containing `analysis_id`, `run_id`, `status`, `mode`, `provider`, `model`, `uncertainty`, typed attributions, refusal records, and safe provenance checksums.
- The object is derived from the latest PostgreSQL `ModelAnalysisAudit`; it contains no raw provider narrative or chain-of-thought.

- [ ] **Step 1: Write the failing backend read-model test.** Seed or construct a `ModelAnalysisAudit` returned by the existing model-run repository and assert `LocalDemoRuntime.operator_view` includes the latest persisted analysis ID/run ID, typed attribution labels, uncertainty, terminal outcome, and PostgreSQL authority marker after a fresh run.

```python
def test_authoritative_operator_view_includes_latest_persisted_agent_analysis(runtime, persisted_case):
    view = runtime.operator_view("tenant-1", "case-1")

    assert view["authoritative"] is True
    assert view["agent_analysis"]["analysis_id"] == "analysis-1"
    assert view["agent_analysis"]["run_id"] == "agent-run-1"
    assert view["agent_analysis"]["attributions"][0]["label"] == "uncertain"
    assert view["agent_analysis"]["provenance"]["authoritative_store"] == "postgresql"
```

- [ ] **Step 2: Run the focused backend test and verify it fails for the missing field.**

Run: `pytest tests/acceptance/test_runtime_product.py -k persisted_agent_analysis -q`

Expected: FAIL with a missing `agent_analysis` key, or collect the focused new test if the existing fixture does not expose the runtime seam.

- [ ] **Step 3: Implement a redacted read-model adapter.** Add a helper beside the existing local-runtime payload helpers that reads only `ModelAnalysisAudit` fields and the safe `typed_response` provenance. Derive `run_id` from `audit.provenance["agent_run_id"]`, map `audit.terminal_outcome` exactly, and return `None` when no model audit exists. Include the result in `operator_view`; do not alter the PostgreSQL repositories or replay adapter.

- [ ] **Step 4: Add the matching Zod schema and render contract test data.** Make `agent_analysis` optional/null in `operatorCaseViewSchema` so pre-analysis cases remain valid. Require typed attribution labels and integer financial metadata only where present; keep all checksums/provenance strings typed.

- [ ] **Step 5: Run backend and frontend focused tests.**

Run: `pytest tests/acceptance/test_runtime_product.py -q`; `npm test -- --run frontend/src/lib/api.test.ts`; `npm run typecheck` from `frontend/`

Expected: the focused backend and frontend suites pass.

### Task 3: Make inbox state, mode labeling, intake refresh, and polling authoritative

**Files:**
- Modify: `frontend/src/components/cases/CaseInbox.tsx`
- Modify: `frontend/src/components/cases/CaseInbox.browser.spec.ts`
- Test: `frontend/src/components/cases/CaseInbox.browser.spec.ts`

**Interfaces:**
- Consumes `listCases` and `getModeAvailability` from Task 1.
- Intake acceptance consumes `IncidentIntakeResponse.case_id`, resets active filters, refetches the first cursor page, and highlights the returned case only if it is present in the fresh response.
- Polling continues only for `queued` and `running`, with one interval and cleanup on dependency/unmount changes.

- [ ] **Step 1: Add failing browser tests for authoritative UI states.** Cover empty page, 503 API error showing “API unavailable”/the existing unavailable message rather than “No cases”, mode label coming from the mode response, intake POST followed by a new first-page GET with cleared filters and highlighted returned case, and `requires_attention` rendering without being polled as active work.

```typescript
test("refreshes and highlights the authoritative case returned by intake", async ({ page }) => {
  let listCalls = 0;
  await page.route("**/tenants/demo-tenant/demo/mode", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ ...modePayload, label: "fresh_agent" }),
  }));
  await page.route("**/tenants/demo-tenant/cases**", async (route) => {
    listCalls += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(listCalls === 1 ? emptyPage : pageWithNewCase) });
  });
  await page.route("**/tenants/demo-tenant/incidents", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(acceptedIntake),
  }));

  await page.goto("/cases");
  await page.getByRole("button", { name: "New incident" }).click();
  await fillRequiredIntake(page);
  await page.getByRole("button", { name: "Accept incident" }).click();

  await expect(page.locator("[data-case-row].case-row--highlighted")).toContainText("case-new");
  await expect(page.getByText("FRESH AGENT")).toBeVisible();
  await expect.poll(() => listCalls).toBe(2);
});
```

- [ ] **Step 2: Run the new browser tests and verify the intended failure.**

Run: `npx playwright test src/components/cases/CaseInbox.browser.spec.ts --grep "refreshes and highlights"` from `frontend/`

Expected: FAIL because the current component keeps filters during acceptance and hardcodes the LIVE READ label.

- [ ] **Step 3: Implement explicit list state behavior.** Replace `getCaseInbox` calls with `listCases`; fetch mode through the same typed gateway without allowing mode failure to turn a valid case page into an empty page; label the header from server mode. On intake acceptance, clear state/automation/search filters before the first-page refetch, set highlight to the returned ID, and set status text to pending until that case is observed. Keep API errors distinct from empty results.

- [ ] **Step 4: Harden polling against duplicate timers and stale responses.** Use one timer for the current tenant/filter scope, clear it in cleanup, and ignore a response that belongs to an older request scope. Keep the 8-second interval only when a visible item has `queued` or `running` orchestration state; do not poll `completed`, `failed`, `awaiting_human`, or `requires_attention`.

- [ ] **Step 5: Run all inbox browser tests and the frontend unit suite.**

Run: `npx playwright test src/components/cases/CaseInbox.browser.spec.ts`; `npm test`

Expected: existing navigation/responsive tests and new authoritative-state tests pass.

### Task 4: Refetch authoritative detail after fresh-agent and control commands

**Files:**
- Modify: `frontend/src/app/cases/[caseId]/page.tsx`
- Modify: `frontend/src/components/agent/FreshAgentPanel.tsx`
- Modify: `frontend/src/components/case/ApprovalPanel.tsx`
- Modify: `frontend/src/components/case/ActionDecisionPanel.tsx`
- Modify: `frontend/src/components/case/EscalationPanel.tsx`
- Modify: `frontend/src/components/audit/AuditTrace.tsx` only if required for explicit loading/error state
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`
- Test: `frontend/src/components/cases/CaseInbox.browser.spec.ts` or a new focused case-detail browser spec

**Interfaces:**
- `CasePage` owns one `loadAuthoritativeView` callback and passes it to every command panel as the refetch callback.
- Command panels display pending/recorded transport state but never assign final case state locally.
- `operatorCaseViewSchema.agent_analysis` drives post-refresh fresh-agent display; embedded `audit` remains the case-detail audit authority.

- [ ] **Step 1: Write failing API/detail tests.** Verify `getCase` requests the authoritative operator-view route, parses a post-fresh-run `agent_analysis`, and that command helpers validate the backend response before returning. Add a browser test that opens a case, runs fresh agent, and observes a second detail GET whose response changes attribution/proposal state; repeat the GET-after-approve path with no optimistic status substitution.

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `npm test -- --run src/lib/api.test.ts`; `npx playwright test src/components/cases/CaseDetail.browser.spec.ts --grep "refetches"` from `frontend/`

Expected: the detail test fails because the current page uses `getOperatorCaseView`, fresh-agent output is only local component state, and the browser fixture has no refetch assertions.

- [ ] **Step 3: Switch the detail page to `getCase` and add stale/refreshing state.** Keep the current view visible during a command-triggered refetch, expose a non-blocking “Refreshing authoritative state…” status, and use the server mode payload for read-only gating. Keep initial loading and missing/permission/API failure states distinct.

- [ ] **Step 4: Update command panels to report transport completion only.** After `runFreshAgent`, approval, rejection, simulator execution, or escalation resolve returns, call the page refetch callback and phrase the message as “request recorded; refreshing authoritative state” until the new view is received. Do not set `view.case.state`, policy, approval, action, verification, escalation, or audit fields in panel-local state.

- [ ] **Step 5: Render latest persisted analysis and embedded audit.** Add a compact fresh-agent summary to the existing detail panel using `view.agent_analysis`; preserve the current visual hierarchy and replay panel. Keep `AuditTrace` driven by `view.audit`; do not call the currently unmounted standalone audit route for normal case detail.

- [ ] **Step 6: Run focused detail tests and frontend checks.**

Run: `npm test`; `npm run typecheck`; `npm run lint`; `npm run build` from `frontend/`

Expected: all commands exit successfully with no weakened existing assertions.

### Task 5: Validate backend seams, connectivity, and repository safety

**Files:**
- Modify only files already listed in Tasks 1–4 if test failures require corrections.
- Do not modify: `AGENTS.md`, `.specify/memory/constitution.md`, ADRs, protected migration paths, `packages/contracts/action_gateway.py`, or unrelated dirty/untracked files.

- [ ] **Step 1: Run backend focused validation.**

Run from the repository root: `pytest backend/tests/integration/test_intake_api.py backend/tests/integration/test_intake_service.py backend/tests/integration/test_inbox_idempotency.py tests/unit/test_case_inbox_boundary.py tests/contract/test_fresh_agent_api.py tests/acceptance/test_runtime_product.py -q`

Expected: all applicable tests pass; environment-dependent tests may skip only for their existing documented reason.

- [ ] **Step 2: Run relevant backend static checks.**

Run: `python -m compileall -q backend packages`; `ruff check backend/api backend/app/cases backend/app/orchestration backend/app/local_runtime.py`

Expected: no compile errors and no new Ruff violations.

- [ ] **Step 3: Verify proxy and localhost/Docker configuration without changing environment-specific URLs.** Confirm browser requests use relative `/tenants/...` paths when `NEXT_PUBLIC_API_BASE_URL` is empty, Next rewrites to `RECLAIM_API_INTERNAL_BASE_URL`, and Compose sets that internal URL to `http://api:8000`; direct localhost remains `http://127.0.0.1:8000` when the API is run outside Compose.

- [ ] **Step 4: Run final diff/status safety checks.**

Run: `git diff --check`; `git status --short`; `git diff --stat -- frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/components/cases/CaseInbox.tsx frontend/src/components/cases/CaseInbox.browser.spec.ts frontend/src/app/cases/[caseId]/page.tsx frontend/src/components/agent/FreshAgentPanel.tsx frontend/src/components/case/ApprovalPanel.tsx frontend/src/components/case/ActionDecisionPanel.tsx frontend/src/components/case/EscalationPanel.tsx backend/app/local_runtime.py docs/superpowers/plans/2026-09-03-case-inbox-api-sync.md`

Expected: only scoped files are changed by this work; protected unrelated paths remain present and unstaged. Do not commit or stage the broad dirty worktree.

- [ ] **Step 5: Report live-browser qualification honestly.** If Docker/API is available, run the supported local stack and the existing Playwright suite against it. Otherwise report mocked/frontend contract validation and the exact environment limitation; never call it live-browser validated.

## Validation Matrix

| Requirement | Evidence |
|---|---|
| Current cursor-paginated cases | Task 1 gateway test and Task 3 browser filter/pagination tests |
| Authoritative case detail | Task 2 read-model test and Task 4 detail refetch test |
| Intake creates and surfaces a real case | Task 3 intake POST → first-page GET → highlight test |
| Exact orchestration status semantics | Task 1 schema test and Task 3 status/polling tests |
| Fresh-agent persistence/refetch | Task 2 persisted-analysis test and Task 4 refetch test |
| Approval/action/escalation refetch | Task 4 command-panel tests |
| Embedded audit/provenance | Task 2/4 detail schema and render assertions |
| API unavailable vs empty | Task 1 HTTP error test and Task 3 empty/error browser tests |
| Localhost/Docker proxy | Task 5 configuration inspection and existing Next config test |
| T153/T154 excluded | Final report and unchanged task markers |

No commit is planned for this implementation because the repository has a broad protected dirty/untracked worktree; stage or commit only a later explicitly selected patch after review.
