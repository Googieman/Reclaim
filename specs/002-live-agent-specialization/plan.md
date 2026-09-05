# Implementation Plan: Live Agent Specialization and Execution

**Branch**: `002-live-agent-specialization` | **Date**: 2026-09-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from [spec.md](./spec.md)

## Summary

RECLAIM already has a bounded LangGraph harness, LiteLLM adapter, redaction layer, strict response/proposal parsing, deterministic attribution/exposure, replay fallback, persistence helpers, and an Action Gateway boundary. The current source-built application intentionally qualifies no provider and mounts only replay/read-model routes, so the agent is not exercised by the usable demo.

This feature reuses those seams. It adds a dedicated `training/reclaim/` pipeline that generates validated examples from approved structured fixtures, a Soup-compatible config and environment record, an evaluator that can compare provider profiles without claiming unavailable training, a logical model-profile resolver, and a fresh-agent coordinator. The fresh route is mounted only when explicitly enabled, executes through the existing LangGraph/LiteLLM boundary, persists an explicit run record, and exposes advisory results. Replay remains a separate deterministic route and is never substituted silently for a failed fresh run.

No new agent framework, database, broker, policy engine, workflow system, shared contract, constitution rule, or ADR is introduced. No protected dirty path is modified.

## Technical Context

**Language/Version**: Python 3.12 for backend/training tooling; TypeScript/Next.js for the operator UI; existing repository supports Python 3.12.

**Primary Dependencies**: Existing FastAPI, Pydantic, Temporal Python SDK, LangGraph, LiteLLM, pytest, and Zod; isolated `soup-cli[train]` only for training and `soup-cli[serve]` only for local model serving.

**Storage**: Existing PostgreSQL model-run persistence when an authoritative repository is supplied; deterministic JSON/JSONL manifests and reports under `training/reclaim/`; local model artifacts in ignored external artifact storage.

**Testing**: pytest unit/contract/integration/security/acceptance suites, frontend Vitest/ESLint/TypeScript checks, dataset validators, Soup data doctor where available, and existing Compose smoke tests.

**Target Platform**: Windows development host and Docker Compose Linux services; local specialist endpoint exposes an OpenAI-compatible interface consumed through LiteLLM.

**Project Type**: Multi-service web application with a Python backend, Next.js operator UI, durable Temporal workflow, and isolated model/Action Gateway boundaries.

**Performance Goals**: Fresh-agent acceptance path completes within the configured model timeout and records actual latency; no release threshold is claimed until measured. Dataset generation is deterministic for a fixed source manifest and seed.

**Constraints**: Model is advisory only; all model input is redacted/bounded; evidence is untrusted; model tools are read-only; deterministic money/policy/approval/execution/verification remain authoritative; live financial actions remain disabled by default; replay and fresh-agent modes must be visibly distinct; no secrets, hidden chain-of-thought, arbitrary network, shell, filesystem, DB write, or mutation credentials enter the model boundary.

**Scale/Scope**: Initial fixture-backed specialization and a runnable minimal fresh-agent path. The pipeline supports grouped development/validation/held-out metadata and real counts but does not fabricate the requested 100+ held-out cases when source data is absent.

## Constitution Check

*GATE: Must pass before implementation. Re-check after design.*

- **I. Defense-Only Operation**: PASS. The model and tools remain restricted to merchant-controlled evidence analysis; no attacker interaction or arbitrary access is added.
- **II. Harnessed Agent and Action Gateway**: PASS. LangGraph/LiteLLM returns typed advisory output; policy, approval, Action Gateway, verification, and audit remain downstream.
- **III. Deterministic Financial Integrity**: PASS. Dataset targets and runtime parsing reject model-supplied money; deterministic exposure/payment state remains authoritative.
- **IV. Authoritative State and Durable Workflows**: PASS. Existing PostgreSQL/Temporal ownership is reused; API coordination does not become business-state authority.
- **V. Event and Projection Ownership**: PASS. No new transport or projection is introduced.
- **VI. Policy, Approval, Idempotency, and Verification**: PASS. Fresh proposals use the existing validator/policy/action boundaries and never auto-approve.
- **VII. Tenant Isolation and Untrusted Evidence**: PASS. Requests and references are tenant/case-bound, contexts are redacted, evidence text is inert data, and provider keys remain outside model input.
- **VIII. Interchangeable Models and Fair Evaluation**: PASS. Logical profiles use one provider interface and identical evaluator inputs; base and specialist are compared with the same harness.
- **IX. Honest Metrics and Reproducible Audit**: PASS. Actual training availability, dataset counts, metrics, and limitations are recorded; no checkpoint or metric is claimed without evidence.
- **X. Test-First and Explicit Decisions**: PASS. New behavior receives focused tests; no material architecture change requires an ADR.

## Existing Audit Classification

| Area | Decision | Reason |
|---|---|---|
| `backend/agent/langgraph_harness.py` | KEEP | Finite graph, explicit budgets, typed checkpoints, no side-effect channel. |
| `backend/agent/litellm_gateway.py` | REWORK | Keep adapter but version a real RECLAIM prompt/profile and local OpenAI-compatible endpoint config. |
| `backend/agent/redaction.py` | KEEP | Existing tenant-bound safe context and deterministic authority constraints cover the new path. |
| `backend/agent/output_parser.py`, `proposals.py` | KEEP | Strict schema, scope, reference, and financial-boundary enforcement is reusable. |
| `backend/agent/replay_fallback.py` | KEEP/REWORK | Preserve explicit fallback semantics; never expose replay as a successful fresh run. |
| `backend/analysis/deterministic_summary.py` | KEEP | Supplies authoritative context and values before the model. |
| `backend/replay/*` | KEEP | Replay remains deterministic and separate. |
| `backend/api/main.py`, `demo.py`, `operator_view.py` | REWORK | Add opt-in fresh-agent route and read model without weakening replay-only defaults. |
| `backend/workflows/*` | REWORK | Add an optional repository-backed analysis activity registration seam; existing default stages remain unchanged. |
| `frontend/src/components/replay/*` | KEEP | Replay UI stays intact; add a sibling fresh-agent panel and truthful mode labels. |
| `packages/contracts/*` | KEEP | No shared contract change is required for the first slice. |

## Project Structure

### Documentation (this feature)

```text
specs/002-live-agent-specialization/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── fresh-agent-api.md
│   ├── specialization-dataset.md
│   └── model-profile-evaluation.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code

```text
backend/agent/
├── langgraph_harness.py
├── litellm_gateway.py
├── model_profiles.py
├── prompts.py
└── fresh_run.py
backend/api/
├── agent_runs.py
└── main.py
backend/workflows/
└── activities/agent_analysis.py
training/reclaim/
├── README.md
├── configs/reclaim-sft.yaml
├── data/sources/
├── scripts/build_dataset.py
├── scripts/validate_dataset.py
├── scripts/evaluate.py
├── manifests/
├── evals/
└── artifacts/.gitkeep
frontend/src/components/agent/
├── FreshAgentPanel.tsx
└── AgentRunBadge.tsx
tests/
├── unit/test_agent_training_dataset.py
├── unit/test_agent_fresh_run.py
├── contract/test_fresh_agent_api.py
├── integration/test_fresh_agent_runtime.py
├── security/test_fresh_agent_safety.py
└── acceptance/test_fresh_agent_demo.py
```

**Structure Decision**: Extend the existing backend agent/API/workflow and frontend case workspace in place. Keep training code, source manifests, reports, and ignored artifacts under a dedicated `training/reclaim/` boundary; never scatter generated data through backend source.

## Delivery Phases

1. **Audit/runtime boundary**: add prompt/version/profile primitives, explicit fresh-run result states, and tests while preserving replay defaults.
2. **Dataset**: generate fixture-backed examples from existing deterministic analysis output; validate schema, references, actions, provenance, leakage metadata, and injection cases.
3. **Soup/evaluation**: create isolated-environment docs/config, run `soup doctor` and data doctor if installable, capture hardware/version, establish an unmodified-base evaluation, and run SFT only if actual prerequisites pass.
4. **Serving/provider**: resolve logical profiles and route local OpenAI-compatible inference through LiteLLM; expose explicit unavailable/fallback states.
5. **Fresh runtime**: provide a bounded coordinator and optional Temporal activity registration, persistence/audit hooks, tenant/case checks, and typed API endpoint.
6. **Operator experience**: add fresh-agent panel/status/provenance and keep replay/action-environment labels distinct.
7. **Hardening/demo/docs**: add injection/provider-failure/tenant/isolation/acceptance tests, evaluate base versus specialist, document actual evidence, and update project status without inventing results.

## Risks and Mitigations

- **Soup cannot run on this host**: isolate install, run doctor, try documented layer streaming only if compatible, and record the exact limitation; do not create a fake checkpoint.
- **Fixture set is too small for claims**: report actual counts and synthetic provenance; use evaluation only as a development signal.
- **Provider output is unsafe**: preserve existing strict parser/proposal validator and fail closed before persistence of accepted proposals or any action.
- **Fresh path accidentally falls back to replay**: fresh coordinator returns explicit unavailable/deterministic-only/escalation status with no replay response substitution.
- **Frontend confuses model execution with action execution**: show separate badges and action-environment copy; keep existing approval/Action Gateway controls unchanged.

## Complexity Tracking

No constitution violations or unjustified complexity exceptions. The new modules are adapters around existing boundaries, not new architecture.
