"""End-to-end generator and validator coverage for the canonical fixture."""

from __future__ import annotations

from pathlib import Path

from training.reclaim.scripts.build_dataset import build_dataset
from training.reclaim.scripts.validate_dataset import validate_dataset


def test_build_then_validate_canonical_fixture(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    manifest = tmp_path / "manifest.json"
    result = build_dataset(
        Path("tests/fixtures/canonical/incident.json"), output, manifest_path=manifest
    )
    report = validate_dataset(output, manifest)
    assert result["rows_written"]["development"] == 1
    assert report["status"] == "valid"
    assert report["held_out_sealed"] is True
