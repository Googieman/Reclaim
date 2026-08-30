# Evidence simulator variants

These replay-only fixtures exercise the same versioned connector response shape
used by live adapters. They contain no credentials and are intentionally
tenant-neutral; the simulator binds the authorized tenant and case at request
time. `timeout`, `unavailable`, and `invalid` fixtures contain no normalized
facts so the orchestrator can surface the limitation without inventing data.
