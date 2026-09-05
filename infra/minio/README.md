# FS-001 MinIO evidence test boundary

This directory reserves the MinIO-specific configuration surface for the US1
evidence provenance tests. Tests use `RECLAIM_MINIO_ENDPOINT`,
`RECLAIM_MINIO_ACCESS_KEY`, and `RECLAIM_MINIO_SECRET_KEY` when a live test
service is explicitly configured; otherwise deterministic in-memory contract
doubles are used and labeled as test data.

No credentials or live deployment claims belong in this directory. The complete
Compose topology remains a later FS-001 task.

Production evidence buckets must use versioning and object lock. Use the
repository backup/restore runbook and `mc mirror --preserve` with an independent
SHA-256 manifest; never treat a MinIO snapshot or graph projection as PostgreSQL
business authority.
