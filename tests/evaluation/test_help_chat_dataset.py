"""The help corpus is complete and the offline runner is honest about gates."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.evaluate_help_chat import load_questions


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "help-chat" / "questions.jsonl"


def test_help_corpus_has_required_partition_counts() -> None:
    rows = load_questions(DATASET)
    assert len(rows) == 75
    assert sum(row["category"] == "supported" for row in rows) == 50
    assert sum(row["category"] == "unsupported" for row in rows) == 20
    assert sum(row["category"] == "adversarial" for row in rows) == 5


def test_offline_runner_does_not_fabricate_metrics(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "evaluate_help_chat.py"),
            "--dataset",
            str(DATASET),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "resource_blocked"
    assert report["metrics"] is None
