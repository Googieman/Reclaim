# Dashboard Help Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the existing bounded help-chat flow as a bottom-right dashboard chatbot backed by the verified DeepSeek-R1-Distill-Qwen-1.5B Q4_0 model and deploy the web, API, gateway, and private model services through Railway.

**Architecture:** The public Next.js web service owns the floating chat control and sends relative `/help/chat` requests. The API authenticates the reviewer and retrieves only reviewed documentation; a private model-gateway service calls the private llama.cpp model service over Railway networking. The model service has no public domain, no tools, and no access to business state.

**Tech Stack:** Next.js 16, React 19, TypeScript, FastAPI, Pydantic, Python 3.12, LiteLLM-compatible HTTP transport, llama.cpp GGUF, Docker, Railway private networking and volume storage, Vitest, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-05-dashboard-help-chat-design.md`

## Global Constraints

- Never commit model weights, API keys, bearer tokens, or Railway secrets.
- The model receives only a normalized question and reviewed documentation passages.
- The chatbot cannot inspect cases, approve actions, execute connectors, mutate business state, or call arbitrary tools.
- Live refunds, cancellations, payments, and other merchant effects remain disabled.
- Model service remains private, authenticated, web-UI-disabled, concurrency-one, and health-checked.
- Unsupported, malformed, uncited, private-reasoning, timed-out, or unavailable model output must become a safe abstention.
- Use integer minor currency units for all existing financial paths; the chatbot must not perform financial calculations or actions.
- Verify every claim with fresh test or browser evidence before reporting completion.

---

### Task 1: Make the help entry point a fixed bottom-right chatbot icon

**Files:**
- Modify: `frontend/src/components/help/HelpChatPanel.tsx`
- Modify: `frontend/src/components/navigation/AppNavigation.tsx`
- Modify: `frontend/src/app/globals.css`
- Test: `frontend/src/components/help/HelpChatPanel.test.tsx`
- Test: `frontend/src/components/navigation/AppNavigation.test.tsx`

**Interfaces:**
- Consumes: existing `HelpChatPanel({ tenantId, initialOpen })` and `askHelp()` contract.
- Produces: a fixed `.help-chat` root with an accessible closed trigger and the existing open panel, mounted outside the transformed navigation rail so it remains fixed on mobile.

- [ ] **Step 1: Write the failing UI tests.** Assert that the closed render contains a fixed-chat trigger class, an accessible `Open documentation help` label, and no visible dialog; assert that `initialOpen` renders the dialog and question form.

```tsx
it("renders a compact bottom-right help trigger when closed", () => {
  const markup = renderToStaticMarkup(<HelpChatPanel tenantId="tenant-1" />);
  expect(markup).toContain("help-chat__trigger--floating");
  expect(markup).toContain('aria-label="Open documentation help"');
  expect(markup).not.toContain('role="dialog"');
});
```

- [ ] **Step 2: Run the focused frontend test and verify it fails for the missing floating class/placement.**

Run from `frontend/`: `npm test -- --run src/components/help/HelpChatPanel.test.tsx`

Expected: FAIL because the current trigger is a navigation-footer control and does not have the floating trigger contract.

- [ ] **Step 3: Implement the smallest UI change.** Keep the existing submit, cancel, retry, abstention, citation, and abort behavior. Add a visually compact icon-only closed state with an accessible label and hidden text; move `HelpChatPanel` out of the `nav-footer`; position the closed trigger fixed at the bottom-right and position the open panel directly above it with mobile-safe dimensions.

- [ ] **Step 4: Run the focused frontend tests and verify they pass.**

Run: `npm test -- --run src/components/help/HelpChatPanel.test.tsx`

Expected: PASS with no test failures.

- [ ] **Step 5: Run the frontend typecheck and lint for the changed UI.**

Run: `npm run typecheck` and `npm run lint` from `frontend/`.

Expected: exit code 0 with no new diagnostics.

- [ ] **Step 6: Commit the UI slice.**

```powershell
git add frontend/src/components/help/HelpChatPanel.tsx frontend/src/components/navigation/AppNavigation.tsx frontend/src/app/globals.css frontend/src/components/help/HelpChatPanel.test.tsx frontend/src/components/navigation/AppNavigation.test.tsx
git commit -m "feat: add floating dashboard help chat"
```

### Task 2: Add the private help-model gateway runtime

**Files:**
- Create: `backend/model_gateway/help_provider.py`
- Create: `backend/model_gateway/main.py`
- Modify: `backend/model_gateway/__init__.py`
- Test: `tests/unit/test_help_model_provider.py`
- Test: `tests/contract/test_help_model_gateway_runtime.py`
- Modify: `backend/pyproject.toml` only if the runtime needs a dependency already used elsewhere but not declared

**Interfaces:**
- Consumes: `HelpGatewayRequest`, `HelpGatewayResponse`, `resolve_profile("reclaim-help-deepseek")`, `MODEL_API_KEY`, and the private llama.cpp OpenAI-compatible `/v1` endpoint.
- Produces: `build_help_provider(environ)` and `create_model_gateway_app()` that serve only authenticated `/v1/help/complete` requests.

- [ ] **Step 1: Write failing provider tests.** Cover prompt construction from only the question/passages, JSON response parsing into `HelpGatewayResponse`, source-id allowlisting, rejection of `<think>`/`<analysis>` markers, missing answer, and model transport failure.

- [ ] **Step 2: Run the focused provider tests and verify the expected failure.**

Run: `python -m pytest tests/unit/test_help_model_provider.py -q`

Expected: FAIL because the provider module and parsing functions do not exist.

- [ ] **Step 3: Implement the provider.** Call the configured OpenAI-compatible model endpoint with a fixed system prompt requiring a JSON object containing only `answer` and `source_ids`; validate output against the requested passage IDs; return `model_revision` from the configured profile; never return raw transport errors or secrets.

- [ ] **Step 4: Write the gateway runtime contract test.** Start `create_model_gateway_app()` with the help provider, assert unauthenticated requests return 401, wrong service tokens return 403, valid tokens return a typed answer, and caller-selected profile/transport fields are rejected.

- [ ] **Step 5: Implement `backend/model_gateway/main.py`.** Resolve the pinned help profile and private endpoint from environment, require `MODEL_API_KEY` and a gateway service token, create the provider, and run Uvicorn on `${PORT:-8001}` without exposing Swagger/OpenAPI.

- [ ] **Step 6: Run provider and gateway tests.**

Run: `python -m pytest tests/unit/test_help_model_provider.py tests/contract/test_help_model_gateway_runtime.py tests/contract/test_help_model_gateway.py -q`

Expected: all focused tests pass.

- [ ] **Step 7: Commit the gateway slice.**

```powershell
git add backend/model_gateway backend/pyproject.toml tests/unit/test_help_model_provider.py tests/contract/test_help_model_gateway_runtime.py
git commit -m "feat: add private help model gateway runtime"
```

### Task 3: Wire the API help route to the private gateway

**Files:**
- Create: `backend/app/help_chat/http_gateway.py`
- Modify: `backend/api/main.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/contracts/test_help_chat_runtime_wiring.py`
- Test: `backend/tests/security/test_help_chat_runtime_wiring.py`

**Interfaces:**
- Consumes: `RECLAIM_HELP_ENABLED`, `RECLAIM_HELP_CHAT_PROFILE`, `RECLAIM_HELP_GATEWAY_BASE`, `RECLAIM_HELP_GATEWAY_TOKEN`, existing `OIDCVerifier`, and `/v1/help/complete`.
- Produces: an API application that mounts `/help/chat` only when enabled and has both a verified identity implementation and a private gateway client.

- [ ] **Step 1: Write failing API wiring tests.** Assert enabled configuration without a verifier or gateway fails closed; enabled configuration creates the route with a fake authenticated verifier and fake HTTP gateway; assert tenant/reviewer authorization and case-context rejection remain intact.

- [ ] **Step 2: Run the wiring tests and verify failure.**

Run: `python -m pytest backend/tests/contracts/test_help_chat_runtime_wiring.py backend/tests/security/test_help_chat_runtime_wiring.py -q`

Expected: FAIL because the production factory does not yet construct the HTTP gateway from environment.

- [ ] **Step 3: Implement the typed HTTP gateway client.** Use a bounded timeout, POST only the `HelpGatewayRequest` JSON to `${RECLAIM_HELP_GATEWAY_BASE}/v1/help/complete`, send the service bearer token, validate the response as `HelpGatewayResponse`, and convert transport/timeout/schema failures to the existing unavailable result path.

- [ ] **Step 4: Wire `create_app()` and the production entrypoint.** Build the HTTP gateway only when help is enabled; keep test callers able to inject a fake gateway; do not enable help by default; preserve existing OIDC requirements.

- [ ] **Step 5: Run the focused API/security tests and the existing help suite.**

Run: `python -m pytest backend/tests/unit/test_help_chat.py backend/tests/contracts/test_help_chat_api.py backend/tests/security/test_help_chat_boundaries.py backend/tests/contracts/test_help_chat_runtime_wiring.py backend/tests/security/test_help_chat_runtime_wiring.py tests/contract/test_help_model_gateway.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the API wiring slice.**

```powershell
git add backend/api/main.py backend/app/config.py backend/app/help_chat/http_gateway.py backend/tests/contracts/test_help_chat_runtime_wiring.py backend/tests/security/test_help_chat_runtime_wiring.py
git commit -m "feat: wire authenticated help chat to private gateway"
```

### Task 4: Make the 1.5B model artifact deployable without committing weights

**Files:**
- Modify: `infra/model-help/entrypoint.sh`
- Modify: `infra/model-help/Dockerfile`
- Modify: `infra/railway/model-help.toml`
- Modify: `infra/docker-compose.yml`
- Create: `scripts/models/verify_help_model.ps1`
- Test: `tests/contracts/test_help_model_deployment.py`
- Modify: `tests/unit/test_help_model_manifest.py`

**Interfaces:**
- Consumes: `models/help-deepseek/manifest.json`, a mounted `/models` directory, and Railway secret/environment values.
- Produces: a private model service that downloads the exact manifest revision once when absent, verifies SHA-256 and size, and starts llama.cpp only after verification.

- [ ] **Step 1: Write failing deployment-contract tests.** Assert the service configuration names the manifest model, uses port 8080 and `/health`, never declares a public domain, and requires a mounted model directory plus `MODEL_API_KEY`.

- [ ] **Step 2: Run the deployment-contract tests and verify failure.**

Run: `python -m pytest tests/contracts/test_help_model_deployment.py -q`

Expected: FAIL for the missing artifact-fetch/checksum contract.

- [ ] **Step 3: Implement checksum-verified model preparation.** Add a script/entrypoint path that downloads the immutable Hugging Face revision only if the GGUF is absent, verifies the manifest SHA-256 and byte size, refuses mismatches, and then starts llama.cpp with the existing no-webui/no-agent/concurrency-one flags. The model gateway uses `RECLAIM_HELP_API_BASE` for this private model endpoint; the API uses `RECLAIM_HELP_GATEWAY_BASE` for the gateway endpoint.

- [ ] **Step 4: Add the private service configuration.** Add a Railway volume declaration at `/models`, set the pinned model URL/revision and checksum as non-secret configuration, keep `MODEL_API_KEY` secret-only, and add the model-help service to the local full Compose profile without publishing its port.

- [ ] **Step 5: Run deployment-contract tests and shell/config checks.**

Run: `python -m pytest tests/contracts/test_help_model_deployment.py tests/contracts/test_help_model_manifest.py -q`; validate the changed TOML/Compose files with the repository’s existing topology checks; run `git diff --check`.

Expected: all checks pass and no `.gguf` file appears under the repository.

- [ ] **Step 6: Commit the model service slice.**

```powershell
git add infra/model-help infra/railway/model-help.toml infra/docker-compose.yml scripts/models/verify_help_model.ps1 tests/contracts/test_help_model_deployment.py tests/unit/test_help_model_manifest.py
git commit -m "feat: prepare private 1.5b help model service"
```

### Task 5: Add deployment variables and operator documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/runbooks/model-services.md`
- Modify: `infra/railway/model-help.toml`
- Modify: `PROJECT_STATUS.md`
- Test: `tests/contracts/test_help_deployment_docs.py` if documentation URL/variable assertions are needed

**Interfaces:**
- Consumes: the public web URL, API URL, private Railway service names, and the manifest model identity.
- Produces: an operator checklist that distinguishes public frontend, public API, private gateway, and private model service.

- [ ] **Step 1: Add the deployment checklist.** Document the exact Railway variables, volume mount, private service references, reviewer authentication prerequisite, and safe smoke-test question. Do not put secret values in the README or docs.

- [ ] **Step 2: Document the bottom-right icon and chatbot scope.** State that the assistant answers reviewed dashboard/documentation questions only and cannot inspect cases or execute actions.

- [ ] **Step 3: Run documentation scans.**

Run: `rg -n -i "localhost|127\\.0\\.0\\.1" README.md`; `git diff --check`.

Expected: no local site address in the public README and no formatting errors.

- [ ] **Step 4: Commit the documentation/configuration slice.**

```powershell
git add README.md docs/runbooks/model-services.md PROJECT_STATUS.md infra/railway/model-help.toml
git commit -m "docs: document deployed dashboard help chat"
```

### Task 6: Run the full relevant verification suite

**Files:**
- Verify: all files changed by Tasks 1–5

- [ ] **Step 1: Run backend help and gateway tests.**

Run: `python -m pytest backend/tests/unit/test_help_chat.py backend/tests/contracts/test_help_chat_api.py backend/tests/security/test_help_chat_boundaries.py backend/tests/contracts/test_help_chat_runtime_wiring.py backend/tests/security/test_help_chat_runtime_wiring.py tests/unit/test_help_model_provider.py tests/contract/test_help_model_gateway.py tests/contract/test_help_model_gateway_runtime.py tests/contracts/test_help_model_deployment.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run frontend tests and quality checks.**

From `frontend/`, run: `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build`.

Expected: all commands exit 0.

- [ ] **Step 3: Run repository diff and artifact checks.**

Run: `git diff --check`; `git status --short`; verify no `.gguf`, `.env`, or secret file is staged.

Expected: only intended source/config/docs files are changed.

### Task 7: Deploy and verify through Railway Computer Use

**Files:**
- External state: Railway `production` environment only
- Evidence: append deployment smoke results to `PROJECT_STATUS.md` after verification

- [ ] **Step 1: Use Computer Use to inspect the existing `perfect-connection` Railway project and preserve the active frontend/API services.** Select the existing Railway project/window and record the current service IDs/domains before changing anything.

- [ ] **Step 2: Create the private `model-help` service using the values in `infra/railway/model-help.toml`.** Enter the Dockerfile path, port, health path, restart policy, and volume mount through Railway’s service configuration UI; do not generate a public domain; attach a persistent volume at `/models`; set non-secret model metadata and secret `MODEL_API_KEY` through Railway’s variables UI.

- [ ] **Step 3: Configure the API service.** Set `RECLAIM_HELP_ENABLED=true`, `RECLAIM_HELP_CHAT_PROFILE=reclaim-help-deepseek`, `RECLAIM_HELP_GATEWAY_BASE` to the private gateway endpoint, and `RECLAIM_HELP_GATEWAY_TOKEN` as a Railway secret. Configure the gateway separately with `RECLAIM_HELP_API_BASE` pointing to the private model service and its model-service credential. Keep all live-action flags false.

- [ ] **Step 4: Deploy the API, gateway/model, and web services in dependency order.** Wait for model health, then gateway health, then API readiness, then web deployment. Use one Computer Use action at a time with a fresh Railway observation after each action.

- [ ] **Step 5: Verify the model service is private.** Confirm no public domain exists for `model-help`; direct public access to `/health` or completion routes must not be available.

- [ ] **Step 6: Verify the public UI.** Open `https://marvelous-truth-production-5c3d.up.railway.app`, confirm the small help icon is fixed at bottom-right, open it, ask a reviewed documentation question, confirm an answer with sources, and confirm an unsupported question produces a safe abstention.

- [ ] **Step 7: Record only observed evidence.** Update `PROJECT_STATUS.md` with service health, deployment revision, UI smoke result, model profile, and remaining qualification gaps. Do not claim production qualification from a single smoke test.

- [ ] **Step 8: Commit the verification record and report the exact URLs.**

```powershell
git add PROJECT_STATUS.md
git commit -m "docs: record deployed help chat smoke test"
```
