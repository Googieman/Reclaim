# US3 containment gate evidence (T103)

Date: 2026-09-01  
Repository: `C:\Users\varug\Reclaim`  
Branch: `main`  
Git HEAD when validation started: `64fc484`  
Scope: T103 only; T104 and all US4 tasks were not started.

## Qualification label

The T103 gate is a deterministic replay qualification. It uses the pinned
repository virtual environment, typed contracts, in-memory authority doubles,
and deterministic action simulators. Every simulated result is labeled
`replay`; no result below is a live PostgreSQL, Temporal, Redpanda, or merchant
provider observation.

## Environment observed

- Windows (`win32`), Python 3.12.13, pytest 8.3.4.
- Ruff was available from the pinned `.venv` and targeted checks passed.
- No `RECLAIM_*DATABASE_URL`, Temporal, or Redpanda endpoint variables were
  configured for this run.
- Docker Desktop was available, but no containers were running and this
  repository has no US4 Compose topology to qualify.
- The `psql`, `temporal`, and `rpk` command-line clients were unavailable.

## Gate observations

Command:

```text
.\.venv\Scripts\python.exe -m pytest tests/integration/test_us3_containment_slice.py --tb=short
```

Observed result: **1 passed, 1 warning**. The warning was the existing
LangGraph pending-deprecation warning during import.

The test measured and asserted the following outcomes:

- Two typed proposals validated as `valid`, policy-ready, and replay-labeled;
  the model request allowed only `read_evidence` and `propose_action`.
- Policy results covered `allow`, `approval_required`, `deny`, and `escalate`.
  The decision retained the policy version and immutable checksum.
- One self-approval attempt was rejected. One distinct authenticated approver
  produced an exact, store-backed approval. No approval bypass was accepted.
- Deterministic integer-minor-unit exposure was INR 50,000 gross, INR 20,000
  contained, INR 30,000 remaining, and INR 2,499 legitimate value disrupted.
- The UNKNOWN session result was persisted before recovery. Recovery performed
  reconciliation once, performed no retry, made zero recovery invokes, and
  retained one provider attempt.
- The duplicate semantic session request converged to the same execution;
  duplicate effect count was `0`, with one simulator connector call and one
  simulated remote effect.
- The session verifier returned `verified_success`; the fulfillment verifier
  returned `inconclusive`, which routed to a tenant-scoped escalation owned by
  `escalation-owner-us3`.
- Terminal outcomes were exactly `verified_contained` and
  `escalated_unresolved`; the generic `closed` alias was rejected.
- Three forbidden execution attempts were rejected: direct gateway use by a
  reviewer, control-plane submission without a service identity, and a refund
  submission without approval. Connector call counts remained unchanged.
- The Action Gateway exposed only the two defensive simulator connectors; live
  actions and live financial actions were both disabled by default.
- The audit trace contained 14 checksum-linked append-only records and the
  outbox contained 10 tenant/case-bound events. Serialized trace values
  contained no secret, credential, password, raw, email, phone, or PII field.

## Regression and quality evidence

Observed with the pinned `.venv`:

- T087 acceptance: `1 passed, 1 warning`.
- Available US3 suite including T103: `87 passed, 1 warning`.
- Available US2 regressions: `13 passed, 7 skipped, 1 warning`. Skips were
  configured fresh-migration/RLS/PostgreSQL checks requiring absent database URLs.
- Contract registry and Action Gateway contract tests: `14 passed`.
- US3 migration/RLS unit inventory: `4 passed`.
- Full Python suite: `500 passed, 40 skipped, 1 warning`.
- Targeted Ruff check and format check: passed.
- `compileall -q backend packages tests`: exit code 0; Python reported only
  `Can't list 'backend\\.pytest_cache'` while traversing a cache directory.
- `pip check`: passed with no broken requirements.
- Package/import smoke: passed; it emitted the same LangGraph warning.
- `git diff --check`: exit code 0; Git emitted only existing line-ending notices.
- No configured mypy executable was available, so no type-checker result is
  claimed.

## Live qualification boundary

The configured live PostgreSQL/fresh-migration, non-owner RLS, Temporal,
Redpanda, and merchant-provider checks were not executed because their
endpoints/credentials and required CLIs were absent. This evidence therefore
does not claim live-service readiness or live financial execution. The
pre-existing untracked `security-audits/` directory was preserved.
