# Analysis, Proposal, Policy, and Approval Contract

## Model analysis request

Includes redacted structured case representation, tenant/case identity, evidence references, allowed read/proposal tools, policy version, model budget, provider mode, and replay/live label. It never includes Action Gateway credentials or unrestricted network/tool capability.

## Model analysis response

Includes schema version, provider/model metadata, event attribution suggestions, rationale/evidence references, uncertainty, typed action proposals, refusal/forbidden-attempt records, token/cost metadata where available, and no executable free-form side effect instruction.

## Typed proposal

Required fields: proposal identity, case/tenant, allowlisted action type, target resource, bounded parameters, evidence/rationale references, requested amount/currency where relevant, idempotency key, and originating analysis identity.

## Policy decision

The deterministic evaluator receives proposal, tenant, resource state, attribution/confidence, amount, reversibility, customer impact, approvals, and immutable policy version. It returns exactly one of `allow`, `deny`, `approval_required`, or `escalate`, with evaluated conditions and audit identity.

## Approval

Approval includes authenticated approver, role, scope, policy version, expiry, and proposer identity. The evaluator rejects self-approval and stale/revoked approval. Cancellation, refund, and identity-affecting restoration always require policy-valid approval.
