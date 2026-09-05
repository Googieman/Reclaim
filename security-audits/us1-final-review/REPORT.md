# RECLAIM US1 final engineering and security review

Review date: 2026-08-31
Scope: T001-T058, remediation history through `4502698`; T059/US2 not started.
Mode: read-only.

## Executive summary

US1 is substantially implemented and the main authority/tenant/integrity boundaries
are present. The real production Temporal CaseWorkflow, worker registration, durable
evidence/timeline activities, PostgreSQL re-read, outbox, Redpanda reconciliation,
and Neo4j projection path are implemented and were previously demonstrated live.
Current local tests/build checks pass as documented, but live services are not
configured in this review. Two material defects remain after independently checking
the remediations: concurrent first audit writes can create multiple roots in a tenant
audit chain, and a conflicting-source timeline's uncertainty is dropped when the
production persistence/outbox path is used. In addition, MAJOR-5 is only partially
closed: same-tenant case-only webhook association is accepted without proving the
provider event belongs to that case. These are relevant to US2 trustworthiness; T059
remains blocked.

## Confirmed findings

| ID | Classification | Status | Summary |
|---|---|---|---|
| US1-F-001 | MAJOR | OPEN | Audit-chain root race allows multiple null-predecessor roots for one tenant. |
| US1-F-002 | MAJOR | OPEN | Timeline uncertainty is not carried into authoritative persistence/outbox. |
| MAJOR-5 | MAJOR | PARTIAL | Same-tenant case-only webhook association is not correlated to the provider event. |

### US1-F-001 — concurrent audit-chain roots

Affected locations: `backend/app/audit/chain.py:44-96`,
`backend/app/intake/service.py:74-145`, and
`backend/db/migrations/001_authoritative_entities.sql:278-305,403-405`.

`AuditChain.build_record` reads the latest checksum and `append` reads it again,
but there is no per-tenant serialization. The database has a uniqueness index for
non-null predecessors only; its partial predicate explicitly permits multiple
`NULL` predecessors. A source-level interleaving was reproduced with two records
built before either append: both had `previous_record_checksum=None`.

Realistic scenario: two authenticated reviewer intake requests for different new
incidents in the same tenant overlap before either transaction commits. Both create
audit records with no predecessor and both can commit. The resulting tenant history
has two roots, so a reviewer cannot follow one append-only chain through all intake
records. The non-root duplicate-predecessor case is better protected by the unique
partial index; the initial-root case is not.

Minimal remediation: serialize the first/latest read and insert per tenant using a
locked tenant-chain anchor or transaction advisory lock, and retain a retry path for
unique-predecessor conflicts. A migration/implementation change is required; no
contract or ADR change is required.

### US1-F-002 — uncertainty dropped at persistence/outbox handoff

Affected locations: `backend/timeline/reconstruct.py:37-118,124-181` and
`backend/app/events/timeline_events.py:87-103`.

`TimelineReconstructor.rebuild` correctly detects a conflicting source and returns
for example `('payment-1:conflicting_sources',)`. Its `_persist` method writes event
fields without the conflict/uncertainty fields and constructs a new
`TimelineRebuildResult` without passing the computed `uncertainty`. The event builder
then serializes that new result, producing `payload['uncertainty'] == []`. A direct
read-only harness using two conflicting `NormalizedFact` values observed exactly
this mismatch: returned uncertainty was non-empty, outbox uncertainty was empty.

Realistic scenario: an untrusted or inconsistent connector supplies two facts with
the same dedupe key and different payloads. US1's pure reconstruction marks the
event uncertain, but the production persistence/outbox handoff does not preserve
the case-level uncertainty. A future US2 attribution/policy consumer can therefore
receive authoritative-looking timeline data without the required uncertainty flag,
violating FR-010 and risking a certain malicious/legitimate classification.

Minimal remediation: persist the complete uncertainty/conflict representation in
PostgreSQL, pass the original result (or its complete uncertainty) to the outbox
builder, and add an integration test that reads both persisted rows and the emitted
payload. Contract/schema review is required if the existing timeline table/event
contract is extended; an ADR change is not inherently required unless ownership or
representation changes.

### MAJOR-5 — same-tenant webhook association remains partial

Affected locations: `backend/app/intake/webhook_processing.py:73-85,161-180,245-277`
and `tests/unit/test_webhook_processing.py:259-270`.

The service accepts `incident_id` and `case_id` as caller-supplied arguments. With a
case ID, `_resolve_association` looks up that case, checks that it exists in the
authenticated tenant, derives its incident, and accepts the mapping. It does not
prove that the verified provider event or request correlation belongs to that case.
The unit test explicitly treats case-only selection as valid. Therefore a same-tenant
caller can present a valid webhook for one case and attach it to another existing
case; the pair-mismatch and cross-tenant defenses do not address this single-ID path.

Realistic scenario: a reviewer-facing integration or future webhook route passes a
valid provider webhook plus `case_id=case-2` while the event is associated with
case-1. The provider verifier authenticates the payload, the case exists in tenant-a,
and the delivery is durably stored against case-2. This corrupts case evidence
association without crossing RLS.

Minimal remediation: derive the association from an authoritative provider-event or
correlation mapping and reject/quarantine when the mapping is absent; do not accept a
caller-selected case as sufficient. A contract change is required if the request must
carry an explicit correlation identity or if a new provider-to-case mapping contract
is introduced; no ADR change is inherently required.

## MAJOR-1 through MAJOR-10 re-verification

Nine previous major findings are closed in the current US1 implementation. MAJOR-5 is
only partially closed:

1. **CLOSED** — production CaseWorkflow and worker register real evidence/timeline
   activities; final PostgreSQL state is re-read and must be `timeline_ready`.
2. **CLOSED** — PostgreSQL outbox is authoritative; exact reconciliation and tenant,
   service, and producer checks precede projection mutation. Broker-native mTLS/SASL/
   ACL is not implemented and is not credited.
3. **CLOSED** — stable identity/checksum tie-breaking and final sort are independent
   of input order.
4. **CLOSED** — inline reports are retained as immutable MinIO objects with checksum
   references; raw content is excluded from audit/events/logging.
5. **PARTIAL** — cross-tenant and mismatched incident/case references fail, but a
   caller-selected same-tenant case-only association is accepted without an
   authoritative provider-event/correlation match. This is the remaining prior major.
6. **CLOSED** — explicit global/tenant policy scope, RLS, cross-scope FKs, published
   immutability, stable child references, and append-only decisions are enforced.
7. **CLOSED** — PostgreSQL composite relationships and authorization trigger enforce
   tenant/case/proposal/decision/approval/execution/verification integrity; allow,
   exact approved approval, deny, escalate, stale, and substitution cases were
   directly tested in the recorded live matrix.
8. **CLOSED** — HTTP, intake, webhook, connector, and raw-object byte boundaries
   reject exact over-limit input before downstream state/storage side effects.
9. **CLOSED** — MinIO uses conditional create semantics; same-content duplicates are
   safe and conflicting concurrent writes cannot replace the owner.
10. **CLOSED** — clean wheel/sdist builds and isolated installed-artifact imports
    include runtime modules while excluding tests, audit artifacts, secrets, and pyc.

## Architecture and security assessment

PostgreSQL ownership, RLS, composite aggregate relationships, outbox/inbox semantics,
Temporal recovery, tenant-bound OIDC contexts, raw evidence provenance, MinIO
immutability, and defensive-only capability boundaries are strong. Redpanda offsets,
ACKs, and Neo4j state do not establish business completion. No offensive capability,
financial mutation, account mutation, model inference, or Action Gateway execution
exists through T058.

Residual hardening notes, not additional current-gate majors: malformed broker JSON
fails before the inbox/DLQ path; direct Neo4j adapter methods can be miswired outside
the dispatcher; Neo4j accepts snapshots without a freshness guard; evidence
collection does not preflight case existence; optional same-tenant webhook association
does not prove correlation linkage; the accepted webhook raw reference is an object key
where the field name suggests a URI; Redis lock release is not token-checked; the
default HTTP body limit is broader than the report-field limit; future workflow
signals are not yet authoritative action commands; and type checking is unavailable.
These are tracked as MINOR/INFO below because current US1 controls prevent them from
becoming an authority or side-effect bypass; MAJOR-5 is excluded from that list because
its association-integrity gap is material.

## Finding counts and classification

- **BLOCKER:** 0 new.
- **MAJOR:** 2 new confirmed findings (US1-F-001 and US1-F-002), plus 1 prior
  finding still PARTIAL (MAJOR-5).
- **MINOR:** 6 tracked issues: evidence collection lacks a case-existence preflight;
  malformed broker messages bypass durable inbox/DLQ handling; Neo4j has no timeline
  snapshot freshness guard; no static typecheck is available; boundary tests still
  leave fake/reference/live-content gaps; and future workflow/approval identity is not
  yet an authoritative authenticated control.
- **INFO:** 8 hardening/deployment notes: broker-native mTLS/SASL/ACL is absent by
  design in this development setup; direct Neo4j ingress lacks independent outbox
  reconciliation; low-level tenant-string APIs merit further narrowing; Redis lock
  release is not token-checked; the HTTP body default exceeds the report-field limit;
  webhook object-key/URI naming is inconsistent; raw objects can be orphaned if the
  later database transaction rolls back; and HS256 remains configurable for OIDC.

## Test-quality assessment

The suite does more than count records: it uses production reconstruction/orchestration
classes, property permutations, direct SQL integrity cases, conditional-write race
tests, exact boundary tests, real Temporal/Redpanda/Neo4j/MinIO paths in opt-in tests,
and installed-artifact imports. Weaknesses remain: many local tests use recording/fake
UoWs or fake Neo4j drivers, direct Neo4j adapter tests bypass outbox reconciliation,
the live T058 gate does not query actual Neo4j node contents, and no test exercises
concurrent audit appends or persisted uncertainty. T043's namespace isolation is
correctly documented as a clean-volume harness model; it does not mask a production
replay correctness claim, but a populated-case rerun is intentionally not accepted.

## Build and typing

Current `.venv` checks: `233 passed, 25 skipped`; compileall passed; pip check passed.
Production-scope Ruff reports 16 pre-existing findings and format check reports six
files needing formatting; repository-wide lint/format therefore do not pass cleanly.
Wheel/sdist and isolated import smoke passed in the suite. No mypy or pyright
executable is available, so no static-type pass is claimed. This is acceptable as
tracked technical debt for T059 only if US2 adds boundary typing and a real typecheck;
it is a meaningful US2 risk at model/policy/action interfaces.

## Gate decision

**KEEP T059 BLOCKED.** The two newly confirmed majors and the partially closed MAJOR-5
are current correctness/integrity defects, not merely deployment hardening. T059 must
not begin until all three are repaired, covered by direct tests, and the full US1 gate
is rerun with actual authoritative state checks.

## Before US3/action execution

At minimum: close the audit-root race; preserve uncertainty through PostgreSQL,
outbox, projection, attribution, policy, escalation, and audit; implement positive
allowlisted Action Gateway authority with reconciliation/idempotency/verification;
validate approver role and separation of duties; bind broker-native service identity
where deployment requires it; add type checking and frontend/CI gates; and run live
failure/recovery tests without claiming replay or simulator results as production
fraud performance.
