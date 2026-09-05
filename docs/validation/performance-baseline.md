# FS-001 measured performance baseline

This is an observed local baseline from the actual in-memory simulator intake,
deterministic replay, and action-recovery callables. It is not production fraud
or containment performance and it does not establish an SLO.

## Qualification and environment

- Measurement date: 2026-09-02.
- Host/runtime: Windows 11 (`10.0.26200`), Python `3.12.13`.
- Runner: `pytest-local-inmemory-deterministic`.
- Dataset: one canonical fixture case, `tests/fixtures/canonical/incident.json`.
- External services: not used; no PostgreSQL, Temporal, Redpanda, Neo4j, MinIO,
  Redis, Keycloak, Vault, hosted model, or merchant connector latency is
  represented.
- Conditions: one warm process; intake 3 warmups plus 25 measured repetitions;
  replay 2 warmups plus 10 measured repetitions; recovery 1 measured operation
  plus 1 supplied recovery callable. Failures remain in the denominator.

## Observed measurements

| Callable | Samples | Warmups | p50 (ms) | p95 (ms) | Throughput (/s) | Failures | Failure rate | Recovery (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| In-memory simulator intake | 25 | 3 | 0.084100 | 0.117320 | 10666.894 | 0 | 0.0 | n/a |
| Deterministic replay | 10 | 2 | 7.866150 | 8.921765 | 124.894 | 0 | 0.0 | n/a |
| Action recovery simulator | 1 | 0 | 0.115800 | 0.115800 | 8576.330 | 0 | 0.0 | 0.091600 |

The intake p95 (`0.000117320` seconds) is within the provisional `<=2 seconds`
design comparison. The replay p95 (`0.008921765` seconds) is within the
provisional `<=5 minutes` design comparison. These are callable-level local
comparisons only, not release-SLO claims.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m pytest tests/performance/test_fs001_baseline.py -q -s --tb=short
```

The test records the full measurement dictionaries as pytest properties and
prints them in the test output. Its timing scope is the supplied callable only;
the recovery value is populated by an actual deterministic `recover_action`
call with an unknown remote result reconciled to `not_found`.
