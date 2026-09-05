# US1 final review finding details

## US1-F-001 — concurrent audit-chain roots

Trace:

1. `backend/app/intake/service.py:74`, `IncidentIntakeService.accept`, accepts an
   authenticated intake and opens a tenant-scoped UoW.
2. `backend/app/intake/service.py:130`, `_append_intake_audit`, creates an audit
   record for the intake inside that UoW.
3. `backend/app/audit/chain.py:64`, `AuditChain.build_record`, reads the latest
   tenant checksum; two overlapping first writes can both observe `None`.
4. `backend/app/audit/chain.py:89-96`, `AuditChain.append`, rechecks the stale
   `None` value and inserts the record without a serialization primitive.
5. `backend/db/migrations/001_authoritative_entities.sql:403-405`, the unique
   predecessor index excludes `NULL`, so two root records are not rejected.

The direct harness used during this review built two records against a repository
whose latest read remained empty and observed:

```text
[('audit-a', None), ('audit-b', None)]
```

This is a concurrency-dependent integrity defect requiring two authenticated
requests for the same tenant; it is not an unauthenticated privilege escalation.

## US1-F-002 — uncertainty dropped at persistence/outbox handoff

Trace:

1. `backend/timeline/reconstruct.py:37`, `TimelineReconstructor.rebuild`, groups
   normalized facts and detects differing payloads for one dedupe key.
2. `backend/timeline/reconstruct.py:76`, the result records a case uncertainty such
   as `payment-1:conflicting_sources`.
3. `backend/timeline/reconstruct.py:105`, the production persistence path calls
   `_persist` after building the correct in-memory result.
4. `backend/timeline/reconstruct.py:134-158`, `_persist` writes timeline rows but
   does not pass conflict/uncertainty fields to the repository.
5. `backend/timeline/reconstruct.py:162-171`, `_persist` constructs a new result
   with `normalized_facts=()` and no `uncertainty` argument.
6. `backend/app/events/timeline_events.py:100`, the event builder serializes that
   new result and emits an empty uncertainty list.

The direct harness used during this review observed:

```text
returned uncertainty= ('payment-1:conflicting_sources',)
outbox uncertainty= []
```

This is a normal conflicting-evidence scenario, not a malformed-input edge case.
It matters before attribution/policy because FS-001 FR-010 requires uncertainty to
remain explicit rather than silently becoming a certain label.

## MAJOR-5 — same-tenant case-only webhook association

Trace:

1. `backend/app/intake/webhook_processing.py:73`, `WebhookProcessingService.process`,
   accepts a verified webhook plus caller-supplied optional `incident_id`/`case_id`.
2. `backend/app/intake/webhook_processing.py:161-166`, the service resolves those
   IDs before durable delivery creation.
3. `backend/app/intake/webhook_processing.py:260-267`, a supplied case ID is looked
   up and checked only for tenant ownership/existence.
4. `backend/app/intake/webhook_processing.py:268-277`, the case's incident is derived
   and returned without provider-event or request-correlation ownership validation.
5. `backend/app/intake/webhook_processing.py:168-180`, the verified delivery is
   persisted against that selected case.

The current unit test at `tests/unit/test_webhook_processing.py:259-270` explicitly
accepts case-only association. The pair-mismatch test at `:273-287` proves only that
two supplied IDs must agree; it does not prove that a single same-tenant case ID is
the correct case for the provider event.

This is a partial closure of the previous MAJOR-5 finding: tenant and pair integrity
are improved, but arbitrary same-tenant case substitution remains possible at this
service boundary. The current tree has no public webhook HTTP route, so deployment
routing still determines reachability; the service contract itself does not establish
the required association invariant.
