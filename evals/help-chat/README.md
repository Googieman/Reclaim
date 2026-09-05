# Help-chat evaluation

`questions.jsonl` is a reviewable, versioned smoke corpus for the bounded
documentation assistant. It contains 50 supported documentation questions, 20
unsupported questions, and five adversarial boundary probes. The expected
statuses are test expectations, not model results.

Run the offline corpus check with:

```powershell
python scripts/evaluate_help_chat.py --dataset evals/help-chat/questions.jsonl --output evals/help-chat/reports/local.json
```

That command validates the corpus and records that no live model was invoked.
To measure an actual authenticated endpoint, pass `--url` and a bearer token;
the runner records only observed response statuses and never turns a failed
request into a fabricated score.

The initial report is intentionally `resource_blocked`: no model weights were
downloaded, no paid/private model service was provisioned, and no live
authenticated help endpoint was available in this worktree.
