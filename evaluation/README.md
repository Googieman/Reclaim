# Evaluation manifest and benchmark boundary

`manifest.yaml` is the source-of-truth metadata for an evaluation corpus. This
checkout contains no labeled benchmark corpus, so the manifest reports
`case_count: 0` and the resulting shortfall honestly. The canonical incident
fixture is a deterministic demo/replay artifact, not a benchmark or sealed
held-out case.

Allowed provenance categories are `REAL_DISTRIBUTION`, `RAZORPAY_TEST`, and
`SYNTHETIC_OVERLAY`. Raw cases are grouped by merchant/entity and customer and
split temporally before any synthetic overlay is generated. Assignments are
then frozen. A 60/20/20 development/validation/sealed-held-out split and the
500-case target are design targets, not permission to pad the corpus.

Reports include actual sample size, class balance, failed/abstained cases,
confidence-interval limitations, provenance, and whether the result is replay,
synthetic, hybrid, or live-qualified. Evaluation code has no Action Gateway or
database mutation authority.
