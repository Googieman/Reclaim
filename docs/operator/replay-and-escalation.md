# FS-001 replay and escalation guide

## LIVE and REPLAY

`LIVE` is a requested mode, not proof that live work occurred. The server-side
mode selector requires provider and connector availability, qualification, and
an explicitly observed live execution. A live-labelled result is accepted only
from an explicitly qualified live executor that returns live labels and records
live execution.

`REPLAY` runs the versioned deterministic fixture/contracts without connector
credentials or Action Gateway authority. It carries `mode=replay` and
`label=replay`, preserves fixture/provider/policy/model/seed provenance, and
sets side effects and live execution to false. The canonical fixture is
`tests/fixtures/canonical/incident.json`; the replay runner is
`backend/replay/runner.py`.

## Provider or connector unavailable

When a live request is not qualified, `run_live_or_replay` falls back to the
deterministic replay path and records a fallback reason. The public result
cannot be relabeled as live. Depending on the configured fallback policy,
mode selection reports replay or an explicit unavailable/escalation state.
The UI shows the requested, effective, and final modes, availability reasons,
qualification facts, and whether live execution occurred.

Provider unavailability therefore means “use the recorded deterministic path”
or “escalate because qualification failed”; it never means “pretend a provider
answered.” Replay output has no remote side effects.

## Simulation semantics and limitations

Simulation follows the recorded typed stage data and deterministic seed. It can
show the timeline, attribution labels, integer-minor-unit exposure, proposal,
policy, approval, reconciliation, verification, escalation, terminal outcome,
and audit linkage represented by the fixture. It does not invoke a merchant
connector, issue a refund, cancel an order, change an account, or prove that a
merchant state changed.

Replay also cannot prove live latency, provider availability, live credential
scoping, production broker security, production action success, or fraud
precision/recall. Evaluation records retain actual sample counts and current
provenance. The current manifest has zero available cases; target counts are
targets, not results. Synthetic, replay, and Test Mode output must never be
presented as production fraud performance.

## Escalation triggers

The implemented variants and containment services route unresolved conditions
to explicit escalation, including insufficient or partially unavailable
evidence, unknown remote results that remain unresolved, inconclusive merchant
state verification, policy escalation, and unresolved approval-gated work.
An approval-gated action that is not verified is not silently treated as
successful.

An escalation record is tenant- and case-scoped and should include:

- the escalation owner;
- remaining exposure and currency;
- the reason and triggering stage;
- evidence and execution references;
- a recommended human decision; and
- the linked audit/provenance trace.

The operator should review the authoritative case state, inspect the relevant
evidence and verification result, and make the next decision through the typed
authorized API. The agent does not directly resolve escalation or execute the
recommended action.

## UNKNOWN and unresolved verification

`UNKNOWN` means the remote result is not known to be absent or successful. The
Action Gateway persists that state and reconciliation must run before retry.
Duplicate semantic requests must converge on the stable canonical action
identity and must not create duplicate non-idempotent effects.

Verification is mandatory after an attempted action. The result is explicitly
verified success, verified failure, or inconclusive. Inconclusive verification
routes to escalation, with terminal outcome `escalated_unresolved`; it is not a
successful `closed` state.

## Audit trace and final decisions

The append-only audit trace links the flow from intake through terminal outcome,
preserving tenant, case, correlation, evidence, policy, model/provider mode,
approval, execution, reconciliation, verification, escalation, and outcome
references. Replay traces are labeled and non-authoritative. Reviewers should
use the checksum-linked chain and the exact policy/approval/action identities
when explaining a decision.

The T130 acceptance gate
[`test_fs001_complete_flow.py`](../../tests/acceptance/test_fs001_complete_flow.py)
observed the canonical mixed legitimate/malicious/uncertain path, replay
truthfulness, no remote side effects, approval separation, reconciliation before
retry, mandatory verification, escalation, explicit terminal state, and linked
audit. The broader qualification limits are recorded in
[`fs001-quickstart.md`](../validation/fs001-quickstart.md) and
[`performance-baseline.md`](../validation/performance-baseline.md).
