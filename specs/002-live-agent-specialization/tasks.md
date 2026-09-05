# Tasks: Live Agent Specialization and Execution

**Input**: Design documents from `/specs/002-live-agent-specialization/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required by the feature specification and RECLAIM constitution. Test tasks are listed before their implementation tasks within each story.

**Organization**: Tasks are grouped by user story; the first story is the runnable MVP and later stories extend evaluation and operator visibility.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the feature-local directories, ignored artifacts, and reproducible training metadata without altering protected files.

- [X] T001 Create the feature-local training/reclaim directory tree and README in `training/reclaim/README.md`, `training/reclaim/configs/`, `training/reclaim/data/sources/`, `training/reclaim/manifests/`, `training/reclaim/evals/`, and `training/reclaim/artifacts/`.
- [X] T002 [P] Add feature-local training artifact ignore rules in `training/reclaim/.gitignore` for checkpoints, downloaded model caches, generated JSONL, and runtime logs while retaining manifests/configs/reports.
- [X] T003 [P] Record the audited Soup CLI workflow, host hardware gate, base-model selection criteria, and no-claim training policy in `training/reclaim/README.md`.
- [X] T004 Add the exact SFT configuration skeleton with placeholder model/artifact values and documented isolated-environment assumptions in `training/reclaim/configs/reclaim-sft.yaml`.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared model-run, profile, prompt, provenance, and dataset primitives that all stories depend on.

- [X] T005 [P] Add versioned RECLAIM system prompt construction with injection-resistant evidence rules and no-side-effect/model-authority constraints in `backend/agent/prompts.py`.
- [X] T006 [P] Add logical model-profile definitions/resolution for `reclaim-specialist`, `reclaim-baseline`, and explicit fallback configuration in `backend/agent/model_profiles.py`.
- [X] T007 [P] Add explicit fresh-agent run/result states, checksums, safe error handling, and provenance serialization in `backend/agent/fresh_run.py`.
- [X] T008 [P] Add isolated Soup environment capture and model-selection manifest schema in `training/reclaim/scripts/environment.py` and `training/reclaim/manifests/.gitkeep`.
- [X] T009 Add shared test fixtures for a tenant-bound deterministic analysis request and canonical fixture projection in `tests/support/fresh_agent.py` without changing existing fixture contracts.

## Phase 3: User Story 1 - Run a bounded fresh agent analysis (Priority: P1) 🎯 MVP

**Goal**: Execute a real provider call through LangGraph/LiteLLM for an eligible case, return typed advisory output with fresh provenance, and fail closed without replay substitution or side effects.

**Independent Test**: A recording provider completes a canonical tenant-bound request through the fresh coordinator and API; the result is `fresh_agent`, the provider call count is one or more, output is parsed/validated, and no Action Gateway or approval method is called.

### Tests for User Story 1

- [X] T010 [P] [US1] Add prompt/context-boundary tests for inert injection evidence, secret redaction, deterministic financial authority, context-size bounds, and no hidden reasoning in `tests/unit/test_fresh_agent_prompt.py`.
- [X] T011 [P] [US1] Add profile-resolution tests for local specialist, baseline, explicit cloud fallback, missing endpoint, fallback cycles, and secret non-disclosure in `tests/unit/test_fresh_agent_profiles.py`.
- [X] T012 [P] [US1] Add fresh-run unit tests for observed provider execution, malformed output, unknown reference, timeout, unavailable provider, explicit terminal states, and replay non-substitution in `tests/unit/test_fresh_agent_runtime.py`.
- [X] T013 [P] [US1] Add strict API contract tests for tenant/case binding, rejected credentials/raw prompts/action commands, response provenance, and explicit unavailable status in `tests/contract/test_fresh_agent_api.py`.
- [X] T014 [US1] Add integration coverage for LiteLLM → LangGraph → parser/proposal boundary with a recording OpenAI-compatible completion in `tests/unit/test_fresh_agent_runtime.py`.
- [X] T015 [US1] Add safety coverage asserting no Action Gateway, approval, database-write, shell, filesystem, arbitrary-network, or credential capability is available from the model path in `tests/security/test_fresh_agent_safety.py`.

### Implementation for User Story 1

- [X] T016 [US1] Extend `backend/agent/litellm_gateway.py` to use the versioned RECLAIM prompt and optional OpenAI-compatible local endpoint configuration without exposing keys or accepting arbitrary request URLs.
- [X] T017 [US1] Implement `FreshAgentCoordinator` in `backend/agent/fresh_run.py` using `build_analysis_request`, `LangGraphAnalysisHarness`, strict response parsing, and advisory proposal validation only.
- [X] T018 [US1] Add optional repository-backed fresh analysis activity registration in `backend/workflows/activities/agent_analysis.py`, `backend/workflows/activities/__init__.py`, `backend/workflows/worker.py`, and `backend/workflows/commands.py` while keeping existing default stages unchanged.
- [X] T019 [US1] Implement the tenant/case-scoped start/read routes and strict request/response models in `backend/api/agent_runs.py`, including explicit mode/action-environment labels and provider failure semantics.
- [X] T020 [US1] Mount the fresh-agent router only behind explicit non-production configuration in `backend/api/main.py` and add typed settings in `backend/app/config.py` with safe disabled defaults.
- [X] T021 [US1] Add model-run persistence/audit integration through existing repository interfaces in `backend/app/db/repositories/model_runs.py` and `backend/app/audit/model_analysis.py` without altering shared contracts or protected diffs.

**Checkpoint**: The API can complete a fresh recorded-provider run and show explicit unavailable behavior; replay still uses only `ReplayRunner`.

## Phase 4: User Story 2 - Build and evaluate a RECLAIM specialization dataset (Priority: P1)

**Goal**: Generate deterministic, validated train/validation/held-out metadata and safe SFT rows from approved structured fixtures.

**Independent Test**: Build twice from the same fixture and seed, validate both outputs, and compare checksums/provenance while confirming no held-out rows or unsafe capabilities enter training.

### Tests for User Story 2

- [X] T022 [P] [US2] Add dataset schema/provenance/reference/action/financial/secret and injection-case tests in `tests/unit/test_agent_training_dataset.py`.
- [X] T023 [P] [US2] Add split-sealing and entity/customer/time leakage tests in `tests/evaluation/test_agent_dataset_splits.py`.
- [X] T024 [US2] Add a generator/validator integration test using `tests/fixtures/canonical/incident.json` and a deterministic output directory in `tests/integration/test_agent_dataset_pipeline.py`.

### Implementation for User Story 2

- [X] T025 [US2] Implement source loading, deterministic analysis-to-chat-example conversion, concise typed targets, injection examples, and provenance in `training/reclaim/scripts/build_dataset.py`.
- [X] T026 [US2] Implement strict dataset validation, duplicate/reference/action/financial/secret/PII checks, class balance, actual counts, and fail-closed reports in `training/reclaim/scripts/validate_dataset.py`.
- [X] T027 [US2] Implement split-before-overlay metadata and held-out seal checks by adapting existing evaluation split/sealed-store utilities in `training/reclaim/scripts/splits.py`.
- [X] T028 [US2] Add canonical source manifest metadata and generated-output conventions in `training/reclaim/data/sources/README.md` and `training/reclaim/manifests/dataset.schema.json`.

**Checkpoint**: Dataset generation is reproducible and validation reports actual counts and safety/leakage status; absence of a large held-out set is reported, never padded.

## Phase 5: User Story 3 - Compare and promote a specialist honestly (Priority: P2)

**Goal**: Run the same evaluator for base and specialist profiles and produce an evidence-backed SHIP/DON'T SHIP decision; perform real SFT only if Soup prerequisites pass.

**Independent Test**: Two provider profiles produce comparison reports with identical input manifest/evaluator versions and explicit metrics/limitations; no preference tuning is run without legitimate preference pairs.

### Tests for User Story 3

- [X] T029 [P] [US3] Add evaluator metric tests for attribution classes, uncertainty, schema/reference validity, proposal safety, legitimate disruption, injection resistance, latency, and missing token/cost metadata in `tests/evaluation/test_agent_metrics.py`.
- [X] T030 [P] [US3] Add promotion-gate tests for specialist regression, safety regression, no-data limitations, and SHIP/DON'T SHIP output in `tests/evaluation/test_agent_promotion.py`.
- [X] T031 [US3] Add Soup command/config manifest tests that reject unsupported or unobserved checkpoints and record DPO skipped rationale in `tests/integration/test_soup_training_artifacts.py`.

### Implementation for User Story 3

- [X] T032 [US3] Implement the same-harness base/specialist evaluator and metric aggregation in `training/reclaim/scripts/evaluate.py` and `training/reclaim/evals/README.md`.
- [X] T033 [US3] Implement explicit promotion-gate/report serialization with actual counts, confidence/limitation metadata, safety rates, and DPO status in `training/reclaim/scripts/promotion.py`.
- [X] T034 [US3] Run the isolated `soup doctor`, record actual environment metadata, select a hardware/license-compatible base, and update `training/reclaim/configs/reclaim-sft.yaml` only from observed output.
- [X] T035 [US3] Run Soup data doctor and the real SFT command when supported by the isolated environment; record command/runtime/checkpoint/metrics or the exact concrete limitation in `training/reclaim/manifests/training-run.json`.
- [X] T036 [US3] Add ignored artifact provenance and local OpenAI-compatible serving instructions based on the installed Soup CLI in `training/reclaim/manifests/serving.json` and `training/reclaim/README.md`.

**Checkpoint**: A real specialist is promoted only if observed evaluation passes; otherwise the report explicitly says DON'T SHIP or training unavailable.

## Phase 6: User Story 4 - Understand fresh agent versus replay and action state (Priority: P2)

**Goal**: Make fresh model execution, deterministic replay, and action environment visibly distinct in the operator case workspace.

**Independent Test**: UI/API fixtures for replay, fresh success, and provider failure render distinct labels and never expose an automatic approval or mutation shortcut.

### Tests for User Story 4

- [X] T037 [P] [US4] Add API/read-model tests for fresh-agent result fields, action-environment separation, and cross-tenant run reads in `tests/acceptance/test_fresh_agent_demo.py`.
- [X] T038 [P] [US4] Add frontend schema/client tests for fresh-agent status/provenance and replay separation in `frontend/src/lib/api.test.ts`.
- [X] T039 [US4] Add browser/component coverage for fresh-agent loading/error/success and disabled/gated action controls in `tests/browser/test_fresh_agent_operator_workflow.py`.

### Implementation for User Story 4

- [X] T040 [US4] Add typed fresh-agent API client schemas and commands in `frontend/src/lib/api.ts` while preserving replay schemas/routes.
- [X] T041 [US4] Add `FreshAgentPanel.tsx` and `AgentRunBadge.tsx` under `frontend/src/components/agent/` with accessible status/provenance/error copy and separate action-environment labels.
- [X] T042 [US4] Integrate the panel into `frontend/src/app/cases/[caseId]/page.tsx` and styles in `frontend/src/app/globals.css` without redesigning the approved workspace or weakening replay read-only controls.

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Run the complete evidence pass, update traceability/status, and ensure no claims exceed observed validation.

- [X] T043 [P] Add end-to-end safe demo coverage for fresh-agent mixed, uncertain, no-action, provider-failure, and replay cases in `tests/acceptance/test_fresh_agent_demo.py`.
- [X] T044 [P] Add focused regression checks for policy, approvals, Action Gateway isolation, canonical action identity, tenant isolation, and replay in `tests/security/test_fresh_agent_regressions.py`.
- [X] T045 Run dataset validation, Soup/evaluation commands when available, focused/full Python tests, frontend tests/lint/typecheck/build, Compose validation, Ruff/compile checks, `pip check`, and `git diff --check`; retain only observed outputs in `training/reclaim/evals/` and `PROJECT_STATUS.md`.
- [X] T046 Update `training/reclaim/README.md`, `docs/operator/`, `docs/architecture/`, `README.md`, and `PROJECT_STATUS.md` with selected model, actual training/evaluation evidence, serving/fresh/replay commands, limitations, and protected-dirty-path confirmation.

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No feature dependencies; do not modify protected dirty paths.
- **Foundational (Phase 2)**: Depends on Setup and blocks all stories.
- **User Story 1 (Phase 3)**: Depends on the foundational prompt/profile/run primitives; is the runnable MVP.
- **User Story 2 (Phase 4)**: Can use the same foundational context and existing deterministic fixtures; should complete before any training command.
- **User Story 3 (Phase 5)**: Depends on validated dataset output and fresh provider/evaluator seams; training is hardware-gated.
- **User Story 4 (Phase 6)**: Depends on the fresh API contract and can use fixture responses while model artifacts are unavailable.
- **Polish (Phase 7)**: Depends on all implemented stories and actual validation outcomes.

### User Story Dependencies

- **US1 (P1)**: Foundational only; provides the fresh-agent runtime used by US4.
- **US2 (P1)**: Foundational only; produces data used by US3 and is independently testable.
- **US3 (P2)**: Depends on US2 and the profile/evaluator seams; SFT may be explicitly blocked.
- **US4 (P2)**: Depends on US1 API/read-model contracts; no dependency on a successful checkpoint.

### Parallel Opportunities

- T002–T004 can run in parallel after T001.
- T005–T008 can run in parallel; T009 follows the shared primitive shape.
- T010–T015 are parallel test files; T016–T021 are sequential where they touch the same runtime boundary.
- T022–T024 are parallel tests; T025–T028 are ordered by source → split → validation/report.
- T029–T031 are parallel tests; T032–T036 are sequential around observed artifacts/config.
- T037–T039 are parallel tests; T040–T042 are ordered API client → panel → page integration.

## Parallel Example: User Story 1

```text
T010 prompt boundary tests     T011 profile tests
T012 run-state tests            T013 API contract tests
T014 runtime integration        T015 safety boundary tests
```

## Implementation Strategy

### MVP First (User Story 1 + minimum foundation)

1. Complete T001–T009.
2. Complete and validate T010–T021.
3. Demonstrate one recording-provider fresh run and explicit unavailable path.
4. Verify replay regressions and no side effects before continuing.

### Incremental Delivery

1. Add US2 dataset generation/validation and inspect actual counts.
2. Establish an unmodified baseline, then attempt Soup SFT only when doctor/config prerequisites pass.
3. Add base-versus-specialist promotion report and local serving only for observed artifacts.
4. Add UI status/provenance and final safe demo/regression evidence.

## Notes

- Every task includes a concrete path and follows the required `- [ ] T### [P?] [US?] description` format.
- No task authorizes production financial execution, direct model side effects, arbitrary network/tool access, protected shared-contract edits, or opening sealed held-out labels.
- Soup training, DPO, distillation, and GRPO are conditional; missing prerequisites are documented outcomes, not reasons to fabricate a result.
