"""Safety checks for deterministic specialization rows."""

from __future__ import annotations

import json
from pathlib import Path

from training.reclaim.scripts.build_dataset import build_dataset
from training.reclaim.scripts.validate_dataset import validate_dataset

FIXTURE = Path("tests/fixtures/canonical/incident.json")


def test_canonical_dataset_is_reproducible_and_contains_only_typed_targets(
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = build_dataset(FIXTURE, first_dir, manifest_path=tmp_path / "first.json")
    second = build_dataset(FIXTURE, second_dir, manifest_path=tmp_path / "second.json")

    assert (
        first["split_counts"]
        == second["split_counts"]
        == {"development": 1, "validation": 0, "held_out": 0}
    )
    row = json.loads((first_dir / "development.jsonl").read_text(encoding="utf-8"))
    context = json.loads(row["messages"][0]["content"])
    target = json.loads(row["messages"][1]["content"])
    assert context["untrusted_evidence_notice"]
    assert target["schema_version"] == "1.0.0"
    assert all(
        "requested_amount_minor" not in proposal for proposal in target["proposals"]
    )
    assert (
        row["row_checksum"]
        == json.loads((second_dir / "development.jsonl").read_text(encoding="utf-8"))[
            "row_checksum"
        ]
    )


def test_dataset_validator_rejects_tampered_rows(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    manifest_path = tmp_path / "dataset.json"
    build_dataset(FIXTURE, output, manifest_path=manifest_path)
    row_path = output / "development.jsonl"
    row = json.loads(row_path.read_text(encoding="utf-8"))
    row["messages"][0]["content"] = row["messages"][0]["content"].replace(
        "inert", "active"
    )
    row_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    report = validate_dataset(output, manifest_path)
    assert report["status"] == "invalid"
    assert any("checksum" in error for error in report["errors"])
