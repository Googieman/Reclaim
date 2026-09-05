# FS-001 reviewer workflow

This guide describes the implemented T122–T124 operator surface and the n8n-backed
intake/inbox amendment. The browser view is read-only for authoritative case data; consequential commands are typed
API calls and remain subject to backend authorization, policy, approval, and
Action Gateway boundaries.

## Start in the Case Inbox

Open `/cases`. The inbox is tenant-scoped and ordered by `updated_at DESC,
case_id DESC`. Use case-state and automation filters or search by case/incident,
customer, account, order, payment, or external identifier. Narrative content is
never searchable or returned by the inbox endpoint. Select **New incident intake**
to open the keyboard-accessible side panel; on a small screen it becomes a
full-screen sheet.

The required fields are source, incident type, occurred time, and narrative.
Optional references and reported amount/currency are stored as typed intake data;
reported value is explicitly unverified and is not authoritative exposure. On
acceptance, the panel closes, the original case row is highlighted, and an
accessible status announcement confirms the returned case identity. Duplicate
submissions return the original incident/case rather than creating another case.

Queued and running cases refresh automatically. Polling stops at `awaiting_human`,
`completed`, `failed`, or `requires_attention`.

## Follow the n8n handoff

New `incident.accepted` events are consumed by the versioned n8n workflow. n8n
claims the run with its execution ID, asks RECLAIM to normalize the structured
intake, invokes the typed AI endpoint, records deterministic validation/policy
output, and stops at `awaiting_human`. PostgreSQL's orchestration run is the
authority; n8n execution history and Redis queue state are operational metadata.

If a stage or model fails, the error workflow records `requires_attention` with
an allowlisted failure code. It never silently substitutes replay. Approval and
Action Gateway execution remain explicit operator actions.

## Open and scope the case

Open `/cases/{caseId}` in the Next.js operator application. The case workspace
shows the case and incident identity, merchant, tenant scope, owner, typed reported
incident metadata, orchestration status, authoritative refresh time, and whether the displayed result is replay/evaluation
data. The page reads the backend-authoritative case view through
`frontend/src/lib/api.ts`; it does not write case records directly.

## Review the incident and activity

Start in **Incident investigation**. The timeline is chronological and can be
filtered by attribution. For each event, inspect the event identity, source
timestamps, source event IDs, evidence references, checksum/provenance, method
and version, rationale, confidence, and uncertainty reason. Review malicious,
legitimate, and uncertain activity separately. Uncertain activity is not a
fraud verdict and must remain visible when it affects policy or escalation.

Expand a row for technical details when needed. The timeline is a read-only
presentation of authoritative evidence and deterministic reconstruction; it is
not an editor.

## Inspect exposure and policy

The **Financial exposure** panel presents trusted integer minor units and the
currency, including gross exposure, recoverable value, contained value,
legitimate value disrupted, irreversible loss, and remaining exposure. Check
the calculation version and source references before treating a value as a
decision input.

The **Decision / containment** panel presents the exact action packet, target,
amount/currency where applicable, reversibility, customer impact, current
resource state, proposer, policy result, policy version, evaluator, and reason.
The displayed proposal is an explanation of a typed backend proposal, not a
model-controlled command.

## Review or record approval

When policy reports `approval_required`, the **Approval** panel shows the exact
action, target, policy result/version, proposer, approver role, and resource
state. A reviewer may use **Approve exact action** or **Reject exact action**
only when the backend-authorized role and current state permit it. The request
records a decision through the typed approval API; the UI does not mutate an
underlying record or skip policy validation.

Approval permits backend eligibility only. It does not prove that an action was
executed or verified. The proposer and authorized approver must remain distinct.

## Follow the action lifecycle

The lifecycle display is ordered as proposal, policy, approval, gateway,
verification, and terminal outcome. Read `UNKNOWN` as unresolved—not success.
The reconciliation result must be inspected before any retry is considered.
Verification is a separate merchant-state observation and is required after an
attempted action. A verification failure or inconclusive result cannot be
silently shown as success.

## Handle escalation and terminal outcome

The **Escalation** panel appears for unresolved work and shows the tenant-scoped
owner, remaining exposure, reason, recommended next action, evidence references,
and linked execution. If authorized, **Record owner follow-up** records a typed
human decision through the backend API. The agent does not resolve escalation
itself.

The only terminal case outcomes are `verified_contained`, `verified_failed`,
and `escalated_unresolved`. A generic `closed`, `success`, or `resolved` case
label is not an accepted terminal result.

## Inspect replay mode and audit provenance

The **Replay / simulation** panel and mode badge show requested, effective, and
final mode, availability reasons, provider/connector qualification, live
execution occurrence, and live-action enablement. Replay is explicitly labeled
`REPLAY` and states that it has no merchant side effects. **Run simulated
replay** is a typed read/demo command; it does not provide action credentials.

The **Audit trace** is read-only and has narrative and technical-chain views.
Inspect audit ID, actor/action, correlation, evidence, policy/model versions,
previous checksum, and record checksum. Use the audit references to connect the
reviewer's conclusion back to the intake, evidence, analysis, proposal, policy,
approval, action, reconciliation, verification, escalation, and terminal stages.

The UI may display evaluation and replay provenance, but those records are
non-authoritative and synthetic/replay outputs must not be described as
production fraud performance. The observed browser evidence for this workflow
is recorded in [`fs001-quickstart.md`](../validation/fs001-quickstart.md); the
source-level operator boundary is covered by
[`test_operator_workflow.py`](../../tests/browser/test_operator_workflow.py).
