# Feature Specification: Live Agent Specialization and Execution

**Feature Branch**: `002-live-agent-specialization`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Make the RECLAIM agent real: build a provenance-safe specialization dataset and evaluation harness, connect a real open-weight model through LiteLLM and LangGraph, expose a fresh-agent execution path through the existing Temporal/API/UI architecture, and preserve deterministic REPLAY as a separate mode."

## Scope and Boundaries

This feature adds a fresh model-analysis capability to the existing RECLAIM incident workspace. It does not replace the approved case, policy, approval, Action Gateway, verification, audit, or replay architecture. The model is an advisory analyst and recovery planner; deterministic services remain authoritative for identity, evidence references, money, policy, approvals, execution, verification, terminal state, and tenant/case scope.

The first release supports a local open-weight model profile and an explicitly configured provider fallback when available. It includes a reproducible specialization dataset and an honest base-versus-specialist evaluation. It does not claim production fraud performance, enable production financial execution, or require preference tuning when no trustworthy preference pairs exist.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a bounded fresh agent analysis (Priority: P1)

As a fraud or incident-response operator, I want to request a fresh RECLAIM agent analysis for an eligible case so I can see a new evidence-grounded incident summary, attribution, uncertainty, and typed recovery proposals rather than a recorded replay result.

**Why this priority**: The product currently proves deterministic replay but not fresh model participation. A real, bounded model run is the smallest capability that makes the agent operationally real.

**Independent Test**: Given a safe fixture case and a deterministic provider stub that records calls, request a fresh analysis and verify one model execution, a typed result, provider/model provenance, and no side effect or automatic approval.

**Acceptance Scenarios**:

1. **Given** an eligible tenant-scoped case, **When** an authorized operator selects Fresh Agent and submits analysis, **Then** the system executes a bounded model call through the existing model abstraction and returns an explicitly fresh-agent result with provider, model, run state, summary, references, uncertainties, and proposal-validation status.
2. **Given** the model returns a proposal for an unknown event, resource, action, or evidence reference, **When** the result is processed, **Then** deterministic validation rejects it, records the rejection, and sends no mutation request.
3. **Given** the model provider is unavailable or times out, **When** the fresh run ends, **Then** the result is explicitly unavailable, failed, deterministic-only, or escalated according to configured fallback policy and is never mislabeled as replay or success.

---

### User Story 2 - Build and evaluate a RECLAIM specialization dataset (Priority: P1)

As an ML engineer, I want deterministic, provenance-rich training and evaluation data derived from approved structured cases so I can specialize an open-weight model without leaking held-out cases or training on hidden reasoning traces.

**Why this priority**: Specialization is only credible when the data source, split protection, labels, and quality checks are reproducible and auditable.

**Independent Test**: Generate the dataset twice from the same approved source manifests and seed, validate both outputs, and verify identical checksums, valid references, allowed actions only, no secrets/needless PII, no train-held-out overlap, and separate development, validation, and sealed held-out metadata.

**Acceptance Scenarios**:

1. **Given** approved structured fixture/source cases, **When** the generator runs, **Then** it emits structured instruction-response examples using the existing analysis/proposal contracts and records source, scenario, label, split, and generation provenance.
2. **Given** adversarial evidence containing embedded instructions, **When** examples are generated and validated, **Then** the content remains inert evidence data and the target contains no arbitrary tool, network, shell, credential, or unsupported action request.
3. **Given** a held-out case or seed, **When** the training builder is run, **Then** the case is not opened or emitted into training data and the validator reports the held-out seal intact.

---

### User Story 3 - Compare and promote a specialist honestly (Priority: P2)

As a RECLAIM owner, I want to compare the unmodified base model with the specialized model under the same evaluator so I can ship the specialist only when RECLAIM-specific quality improves without safety or legitimate-activity regressions.

**Why this priority**: Training completion is not evidence of usefulness. Promotion must consider uncertain and legitimate cases, forbidden proposals, fabricated references, and injection resistance.

**Independent Test**: Run the evaluator against the same non-held-out evaluation manifest with two provider profiles and verify a provenance-complete comparison report containing metrics, actual sample counts, limitations, and an explicit SHIP or DON'T SHIP decision.

**Acceptance Scenarios**:

1. **Given** base and specialist outputs for the same cases and evaluator version, **When** comparison runs, **Then** it reports attribution precision/recall, legitimate preservation, uncertainty quality, schema/reference validity, proposal validity, forbidden/fabricated output rates, latency, and available token/cost data.
2. **Given** a specialist that improves malicious recall but increases legitimate disruption or forbidden proposals beyond the configured gate, **When** promotion is evaluated, **Then** the report says DON'T SHIP.
3. **Given** no legitimate preference pairs, **When** training planning completes, **Then** DPO is skipped with a recorded reason rather than using arbitrary synthetic preferences as ground truth.

---

### User Story 4 - Understand fresh agent versus replay and action state (Priority: P2)

As an operator, I want the case workspace to distinguish REPLAY, FRESH AGENT, and the separate simulator/Test Mode/live-merchant execution environment so I never confuse a fresh model call with a real financial action.

**Why this priority**: Truthful mode communication is a safety requirement, especially when a fresh model run produces proposals that still require policy, approval, execution, reconciliation, and verification.

**Independent Test**: Open the case UI in replay, fresh-agent success, and provider-unavailable states and verify distinct labels, status copy, result provenance, and disabled/approval-gated controls.

**Acceptance Scenarios**:

1. **Given** a replay request, **When** the workspace renders its result, **Then** it shows REPLAY and recorded-fixture labeling and does not imply a fresh model call.
2. **Given** a completed fresh-agent request, **When** the workspace renders its result, **Then** it shows FRESH AGENT or MODEL RUN plus provider/model provenance, while separately labeling simulator/Test Mode/live-merchant execution state.
3. **Given** a fresh model proposal that requires action, **When** the operator views it, **Then** the proposal remains subject to existing validation, deterministic policy, separated approval, Action Gateway, reconciliation, verification, and audit controls.

### Edge Cases

- The case context is too large: apply a deterministic context bound and fail explicitly without dropping tenant, case, financial, or evidence authority.
- Evidence or model output contains prompt-injection text: retain it only as untrusted content and reject any attempted capability escalation.
- The model returns invalid JSON, unsupported fields, fabricated references, unsupported actions, or model-supplied money: reject the response and preserve deterministic uncertainty/financial values.
- A provider returns a partial or unknown result: use bounded retry/fallback only, reconcile before any non-idempotent retry, and never substitute a replay artifact while labeling the run fresh.
- A case has only legitimate or genuinely uncertain activity: preserve those labels and allow no-action-needed proposals.
- Local model artifacts are absent, too large for the host, or the inference endpoint is down: report model unavailable and retain an explicit deterministic-only or escalation outcome.
- Dataset rows are duplicated or overlap entity/customer/time groups: fail validation before training.
- The training environment is not compatible with the installed training tool: record the exact limitation and do not claim a fine-tuned model.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a tenant- and case-scoped fresh-agent analysis command for eligible cases through the existing durable workflow boundary.
- **FR-002**: System MUST route fresh analysis through the existing LangGraph harness and provider-neutral LiteLLM boundary, with no second agent framework or direct model-to-frontend request path.
- **FR-003**: System MUST send the model only a bounded, redacted structured context containing untrusted evidence labels, authoritative references, deterministic attribution/exposure summaries, policy inputs, and no secrets or unnecessary PII.
- **FR-004**: System MUST keep tenant identity, case identity, timeline ordering, evidence/resource ownership, captured/refunded amounts, currency, exposure, recoverability, policy, approval, execution, verification, and terminal state deterministic and authoritative.
- **FR-005**: System MUST accept model output only through the existing typed response/proposal schemas and deterministic validation of scope, evidence references, timeline/resource references, action allowlist, safe parameters, and financial authority.
- **FR-006**: System MUST keep model tools read-only and allow only the fixed case, evidence, state, exposure, policy-context, and proposal capabilities already permitted by the agent boundary.
- **FR-007**: System MUST enforce explicit budgets for model calls, tool calls, graph iterations, tokens/context, timeout, retry, and malformed/unsupported output handling, and MUST persist an explicit terminal run state.
- **FR-008**: System MUST preserve REPLAY as a deterministic mode with no fresh model call and no remote side effect, and MUST distinguish it from fresh model execution in API, persistence, audit, and UI responses.
- **FR-009**: System MUST record fresh-run provenance including run identity, tenant/case/correlation identity, execution mode, provider, model, adapter/harness/prompt versions, request/output checksums, timing, token/cost metadata when available, and terminal outcome without storing hidden chain-of-thought.
- **FR-010**: System MUST expose explicit provider-unavailable, timeout, malformed-output, forbidden-capability, and deterministic-fallback/escalation outcomes; it MUST NOT silently return a replay result for a failed fresh run.
- **FR-011**: System MUST generate specialization examples from structured approved case data using existing model-analysis and proposal contracts, with concise rationales and evidence references rather than hidden chain-of-thought.
- **FR-012**: System MUST record per-example provenance for source, fixture/source version, synthetic or distribution-derived classification, scenario family, compromise status, split, generation version, and label version.
- **FR-013**: System MUST split and seal evaluation groups before augmentation or variation, prevent train/validation/held-out leakage across entity/customer/time boundaries, and never open held-out labels for training or model selection.
- **FR-014**: System MUST validate dataset schema, duplicates, references, resource IDs, action allowlist, financial consistency, class mix, secret/PII exclusions, injection examples, and actual counts before training.
- **FR-015**: System MUST run and record `soup doctor` and the installed Soup CLI/version behavior before relying on training commands, using an isolated training environment.
- **FR-016**: System MUST evaluate the unmodified base model before training and compare it with the specialist under identical cases, prompts, schemas, tools, deterministic inputs, policies, and evaluator versions.
- **FR-017**: System MUST measure malicious/legitimate/uncertain attribution quality, schema/reference validity, supported/forbidden/unnecessary proposal rates, fabricated evidence/resource rates, injection resistance, legitimate value disrupted, latency, failure rate, and available token/cost data.
- **FR-018**: System MUST produce an explicit SHIP or DON'T SHIP decision and MUST NOT promote a specialist when safety or legitimate-preservation gates regress.
- **FR-019**: System MUST support a local specialist model profile through the existing LiteLLM configuration and an explicit configured fallback profile without placing provider keys in source, frontend, logs, or model context.
- **FR-020**: System MUST keep all fresh-agent proposals subject to existing deterministic policy, separated approval, isolated Action Gateway, reconciliation-before-retry, verification, terminal-state, and append-only audit boundaries.
- **FR-021**: System MUST provide operator-visible fresh-agent status, result provenance, attribution, uncertainties, evidence references, proposal validation, policy result, and action-environment labels without exposing hidden reasoning.
- **FR-022**: System MUST document the selected base model, Soup version, actual hardware, exact training configuration, dataset provenance/counts, baseline and specialist results, training limitations/artifact location, serving command, LiteLLM configuration, fresh-agent path, replay path, fallback path, and known limitations.

### Key Entities *(include if feature involves data)*

- **AgentRun**: One tenant/case-scoped fresh or replay analysis attempt with mode, provider/model provenance, bounded-run metadata, checksums, status, and terminal outcome.
- **SpecializationExample**: One structured instruction-response example with safe case context, typed target output, split, provenance, and validation metadata.
- **EvaluationManifest**: A versioned list of cases and labels used by a reproducible evaluator, including split, group boundaries, held-out seal policy, and metric provenance.
- **ModelProfile**: A logical RECLAIM model name mapped to a provider, model identifier, execution mode, endpoint/configuration reference, and fallback policy.
- **PromotionReport**: A base-versus-specialist comparison with actual counts, metrics, confidence/limitation metadata, and SHIP or DON'T SHIP decision.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the safe fresh-agent acceptance fixture, 100% of successful runs show a recorded fresh model execution with provider/model provenance and no replay label; 0 successful runs report a replay artifact as fresh.
- **SC-002**: 100% of accepted model outputs in the acceptance suite pass typed scope/reference/action validation, and 100% of forbidden, fabricated-reference, or model-money cases are rejected before mutation or approval.
- **SC-003**: Replay regression tests continue to produce deterministic replay-labelled results with zero fresh model calls and zero remote side effects.
- **SC-004**: Dataset generation is deterministic for a fixed source manifest and seed, and validation reports zero held-out leakage, invalid references, unsupported actions, secret fields, or financial-consistency violations.
- **SC-005**: Every training/evaluation example has complete provenance fields and an auditable split; actual counts and shortfalls are reported without padding or fabricated cases.
- **SC-006**: The base-versus-specialist report contains all required attribution, uncertainty, proposal, safety, legitimate-disruption, latency, and available cost/token metrics plus an explicit SHIP or DON'T SHIP decision.
- **SC-007**: The operator can distinguish REPLAY, FRESH AGENT, and simulator/Test Mode/live-merchant execution environment from visible text and structure in every supported state.
- **SC-008**: No fresh-agent path grants the model credentials or direct access to payments, refunds, cancellations, account mutations, database writes, shell, filesystem, arbitrary network, or approval authority.
- **SC-009**: If Soup training cannot run because of a concrete compatibility, dependency, hardware, or artifact limitation, the documentation names that limitation and the repository makes no claim that a specialist checkpoint exists.

## Assumptions

- Existing RECLAIM contracts, agent harness, deterministic analysis, replay runner, Temporal workflow, Action Gateway, API authorization, audit, and operator UI remain the source of truth and are reused.
- The first dataset is built from approved synthetic or fixture cases and any future distribution-derived data is explicitly labeled; it is not production fraud performance.
- Development uses a non-production simulator/Test Mode environment with live financial actions disabled by default.
- Soup CLI is installed only in an isolated training environment; the production backend environment remains free of training-only dependencies.
- The host's available GPU, Python version, dependencies, and model license determine the practical base-model choice. A real training run is attempted only when those prerequisites are met.
- DPO, distillation, GRPO, and cloud-teacher generation are optional and are skipped unless their data quality, support, and safety rationale are independently demonstrated.
- Full observability services are not required for the minimal fresh-agent demo, but fresh-run provenance must remain available through the API/audit boundary.
- Mobile parity and a redesign of the operator workspace are out of scope for this feature.
