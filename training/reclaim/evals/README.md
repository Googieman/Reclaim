# Evaluation artifacts

Evaluation reports compare providers using the same generated rows, bounded context,
prompt, parser, proposal boundary, and evaluator version. A report with
`status: not_run` is an honest absence of model output, not a zero or perfect score.
`promotion.py` emits `SHIP` only when both evaluations ran and specialist safety gates
do not regress. Synthetic/fixture results are not production fraud performance.
