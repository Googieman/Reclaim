# Live Agent Specialization Data Model

## AgentRun

One analysis attempt for a tenant/case/correlation scope. It is distinct from a merchant action execution.

| Field | Type | Rules |
|---|---|---|
| `run_id` | opaque string | Required, unique per attempt. |
| `tenant_id` | opaque string | Required on every run and must match the request. |
| `case_id` | opaque string | Required and bound to the route/request. |
| `correlation_id` | opaque string | Required and preserved through workflow/audit. |
| `execution_mode` | `fresh_agent` or `replay` | Public analysis mode; replay never calls a fresh provider. |
| `provider_mode` | existing provider mode | `live` for a fresh provider adapter, `replay` for fixture provider. |
| `provider` / `model` | strings | Captured from the provider envelope, not trusted request prose. |
| `profile` | string | Logical profile selected by configuration. |
| `prompt_version` / `harness_version` | strings | Versioned provenance. |
| `request_checksum` / `response_checksum` | SHA-256 strings | Stable, redacted request/output identity. |
| `status` | enum | `queued`, `running`, `completed`, `unavailable`, `failed`, `rejected`, `deterministic_only`, `escalation_required`. |
| `proposal_validation` | object | Status/reason only; policy remains downstream. |
| `started_at` / `finished_at` | UTC timestamps | Required when observed. |
| `token_count` / `estimated_cost` | optional numeric | Provider metadata only; never required for correctness. |
| `error` | optional safe string | Must not contain secrets, raw payloads, or hidden reasoning. |

State transitions are monotonic: `queued → running → completed|unavailable|failed|rejected|deterministic_only|escalation_required`. A fresh failure may not transition to `completed` with a replay artifact. `replay` runs are created only by the replay boundary and remain replay-labelled.

## SpecializationExample

One training/evaluation row derived from an approved case representation.

Required provenance fields:

`example_id`, `case_source`, `fixture_version`, `data_class` (`synthetic`, `hybrid`, or `distribution_derived`), `scenario_family`, `compromise_status`, `split`, `generation_version`, `label_version`, `entity_group_id`, `customer_group_id`, and `temporal_boundary`.

The content has two messages:

- `user`: a bounded JSON case context with `untrusted_evidence_notice`, scope, timeline, evidence IDs, deterministic financial authority, policy inputs, and uncertainties.
- `assistant`: a JSON object conforming to the existing model-analysis response/proposal shape, with concise rationales and evidence references. It contains no hidden chain-of-thought, secrets, arbitrary network/tool instructions, model-supplied money, or unsupported actions.

## EvaluationManifest

Versioned manifest containing case/example IDs, split assignment, group IDs, expected labels/outcomes, source checksums, held-out seal policy, and evaluator version. The manifest records actual counts and does not pad missing cases.

Split assignment occurs before overlay/variation generation. A training build may read only `development` rows. Validation may read `validation`. Held-out answers are not available to training or model selection; only sealed IDs/checksums and access-policy metadata are visible.

## ModelProfile

Logical selection record:

`profile_name`, `provider`, `model`, `mode`, `api_base_env`, `api_key_env`, `timeout_seconds`, `max_tokens`, `fallback_profile`, `enabled`, and `profile_version`.

Environment variable names are configuration references, not secrets. The profile resolver rejects unknown profiles, mismatched modes, blank identifiers, and a fallback cycle.

## PromotionReport

Comparison artifact containing `report_id`, `evaluator_version`, `manifest_version`, `case_count`, base/specialist profile provenance, metrics, confidence/limitation metadata, safety-gate evaluation, DPO status/reason, and `decision` (`SHIP` or `DON'T SHIP`). A decision is not valid without actual counts and safety metrics.

## Invariants

1. Every AgentRun, example, manifest row, and audit record has tenant/case/correlation scope where applicable.
2. Every model evidence/timeline/resource reference belongs to the bounded request context.
3. Deterministic exposure and policy values are input authority and cannot be replaced by model output.
4. Only existing allowlisted defensive action types may appear in target/proposal data; refund amount/currency fields are generated downstream from trusted payment state, never from model prose.
5. No row in training overlaps a held-out entity/customer/time group.
6. A fresh-agent success requires an observed provider call and provider/model metadata.
7. No terminal AgentRun status is a merchant action terminal state; that state remains owned by existing policy/action/verification workflows.
