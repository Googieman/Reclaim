"""Evaluator reports no-run truth and observed-response metrics separately."""

from __future__ import annotations

from pathlib import Path

from training.reclaim.scripts.build_dataset import build_dataset
from training.reclaim.scripts.evaluate import evaluate_rows, load_rows


def test_evaluator_does_not_turn_gold_labels_into_model_metrics(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    manifest = tmp_path / "manifest.json"
    build_dataset(
        Path("tests/fixtures/canonical/incident.json"),
        generated,
        manifest_path=manifest,
    )
    rows = load_rows(manifest)
    report = evaluate_rows(rows)
    assert report["status"] == "not_run"
    assert report["scored_count"] == 0
    assert report["metrics"] == {}
