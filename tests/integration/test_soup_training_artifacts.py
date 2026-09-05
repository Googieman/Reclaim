"""Observed Soup artifacts must remain truthful and promotion-gated."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRAINING = ROOT / "training" / "reclaim"


def test_training_manifest_is_observed_and_not_promoted() -> None:
    manifest = json.loads(
        (TRAINING / "manifests" / "training-run.json").read_text(encoding="utf-8")
    )
    artifact = ROOT / manifest["adapter_artifact"]

    assert manifest["status"] == "completed"
    assert manifest["soup_version"] == "0.73.3"
    assert manifest["dataset_rows"] == 1
    assert len(manifest["adapter_sha256"]) == 64
    if artifact.exists():
        import hashlib

        assert (
            hashlib.sha256(artifact.read_bytes()).hexdigest()
            == manifest["adapter_sha256"]
        )
    assert manifest["evaluation_status"] == "not_run"
    assert manifest["promotion_decision"] == "DON'T SHIP"
    limitations = " ".join(manifest["limitations"]).lower()
    assert "one synthetic" in limitations
    assert "not fraud quality" in limitations
    assert "not been promoted" in limitations


def test_soup_config_and_docs_do_not_claim_unobserved_tuning() -> None:
    config = (TRAINING / "configs" / "reclaim-sft.yaml").read_text(encoding="utf-8")
    readme = (TRAINING / "README.md").read_text(encoding="utf-8")

    assert "task: sft" in config
    assert "DPO" not in config
    assert "DPO, distillation, and GRPO are not enabled by default" in " ".join(
        readme.split()
    )
    assert "DON'T SHIP" in readme
