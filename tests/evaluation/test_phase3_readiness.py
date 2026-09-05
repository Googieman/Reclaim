"""Phase 3 fail-closed dataset, evaluation, and promotion gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.manifest import (
    MIN_HELD_OUT_CASES,
    require_qualified_manifest,
    validate_evaluation_manifest,
)
from evaluation.report import build_report
from training.reclaim.scripts.evaluate import compare_reports, evaluate_rows
from training.reclaim.scripts.promotion import validate_model_artifact
from training.reclaim.scripts.build_dataset import build_dataset
from training.reclaim.scripts.validate_dataset import validate_dataset


def _manifest(
    *,
    held_out: int = 100,
    no_compromise: int = 40,
    mixed: int = 50,
    malformed: bool = False,
) -> dict[str, object]:
    development = 20
    validation = 10
    cases = [
        {
            "evaluation_case_id": f"case-{index}",
            "provenance": "approved-test-fixture",
            "split": split,
            "entity_group_id": f"entity-{index}",
            "customer_group_id": f"customer-{index}",
            "temporal_boundary": f"2026-{month:02d}-01T00:00:00+00:00",
            **({"sealed": True, "content_checksum": "a" * 64} if split == "held_out" else {}),
        }
        for index, (split, month) in enumerate(
            [("development", 1)] * development
            + [("validation", 2)] * validation
            + [("held_out", 3)] * held_out
        )
    ]
    if malformed:
        cases[-1]["entity_group_id"] = cases[0]["entity_group_id"]
    total = development + validation + held_out
    return {
        "manifest_version": "evaluation-manifest-v1.0.0",
        "corpus_version": "test-corpus-v1",
        "case_count": total,
        "target_case_count": 500,
        "provenance_categories": ["RAZORPAY_TEST"],
        "label_schema": {
            "attribution_labels": ["malicious", "legitimate", "uncertain"],
            "terminal_outcomes": ["verified_contained", "verified_failed", "escalated_unresolved"],
        },
        "class_balance": {
            "malicious": total - no_compromise,
            "legitimate": no_compromise,
            "uncertain": 0,
            "no_compromise_false_alert": no_compromise,
            "mixed_legitimate_malicious": mixed,
        },
        "split_metadata": {
            "target_ratios": {"development": 0.6, "validation": 0.2, "held_out": 0.2},
            "actual_counts": {"development": development, "validation": validation, "held_out": held_out},
            "assignments_frozen_before_overlay": True,
            "held_out_sealed": True,
        },
        "source_dataset": {"name": "test", "available_case_count": total, "source_references": ["fixture.json"]},
        "synthetic_overlay": {"generated_after_split": True, "available_case_count": 0, "generated_case_count": 0},
        "seed_version": {"seed": "phase3-test", "version": "evaluation-splitting-v1.0.0"},
        "environment_version": "pytest",
        "limitations": [],
        "cases": cases,
    }


def test_manifest_validation_rejects_cross_group_leakage() -> None:
    report = validate_evaluation_manifest(_manifest(malformed=True))
    assert report["status"] == "invalid"
    assert any("group" in error for error in report["errors"])


def test_zero_held_out_corpus_is_valid_metadata_but_not_qualified() -> None:
    manifest = _manifest(held_out=0, no_compromise=0, mixed=0)
    manifest["split_metadata"]["actual_counts"] = {"development": 20, "validation": 10, "held_out": 0}
    manifest["case_count"] = 30
    manifest["cases"] = manifest["cases"][:30]
    report = validate_evaluation_manifest(manifest)
    assert report["status"] == "valid"
    assert report["qualification"]["held_out_minimum"] is False
    assert report["qualification"]["ready_for_model_selection"] is False
    with pytest.raises(ValueError, match="held.out"):
        require_qualified_manifest(manifest)


def test_manifest_requires_no_compromise_and_mixed_composition() -> None:
    report = validate_evaluation_manifest(_manifest(no_compromise=1, mixed=1))
    assert report["qualification"]["no_compromise_composition"] is False
    assert report["qualification"]["mixed_legitimate_malicious_composition"] is False
    assert report["qualification"]["ready_for_model_selection"] is False


def test_qualified_manifest_has_all_split_and_composition_gates() -> None:
    report = validate_evaluation_manifest(_manifest())
    assert report["status"] == "valid"
    assert report["qualification"]["ready_for_model_selection"] is True
    require_qualified_manifest(_manifest())
    assert MIN_HELD_OUT_CASES == 100


def test_report_contains_provenance_and_interval_qualification_metadata() -> None:
    report = build_report(
        [{"actual_label": "malicious", "predicted_label": "malicious"}],
        provenance={
            "dataset_version": "test-v1",
            "manifest_version": "evaluation-manifest-v1.0.0",
            "manifest_checksum": "b" * 64,
            "split": "held_out",
            "model_profile": "base",
            "evaluator_version": "reclaim-agent-evaluator-v2.0.0",
            "environment_version": "pytest",
        },
        seed=7,
    )
    assert report["provenance_complete"] is True
    assert report["confidence_interval_provenance"]["seed"] == "7"
    assert report["actual_sample_size"] == 1


def test_evaluator_marks_missing_and_invalid_outputs_non_complete() -> None:
    row = {
        "example_id": "example-1",
        "messages": [
            {"role": "user", "content": json.dumps({"scope": {}, "timeline": [], "evidence": []})},
            {"role": "assistant", "content": json.dumps({"attributions": [], "proposals": []})},
        ],
    }
    missing = evaluate_rows([row], responses={})
    invalid = evaluate_rows([row], responses={"example-1": {"response": {"not": "typed"}}})
    assert missing["status"] == "incomplete"
    assert invalid["status"] == "invalid"
    assert invalid["invalid_output_count"] == 1


def test_promotion_requires_same_manifest_and_drift_free_qualified_reports() -> None:
    provenance = {
        "manifest_version": "evaluation-manifest-v1.0.0",
        "manifest_checksum": "c" * 64,
        "split": "held_out",
        "actual_sample_size": 100,
        "held_out_count": 100,
        "no_compromise_false_alert_count": 40,
        "mixed_legitimate_malicious_compromised_count": 50,
    }
    metrics = {
        "malicious_recall": 0.8,
        "legitimate_preservation": 1.0,
        "forbidden_proposal_rate": 0.0,
        "prompt_injection_failure_rate": 0.0,
        "schema_valid_rate": 1.0,
    }
    def report(model: str, drift: str = "pass") -> dict[str, object]:
        return {
            "status": "complete",
            "profile": model,
            "metrics": metrics,
            "provenance": {**provenance, "model_profile": model},
            "provenance_complete": True,
            "qualification": {"ready_for_model_selection": True},
            "drift": {"status": drift, "drift_detected": drift != "pass"},
            "invalid_output_count": 0,
            "limitations": [],
        }
    assert compare_reports(report("base"), report("specialist"))["decision"] == "SHIP"
    assert compare_reports(report("base", "fail"), report("specialist"))["decision"] == "DON'T SHIP"
    mismatched = report("specialist")
    mismatched["provenance"] = {**provenance, "manifest_checksum": "d" * 64, "model_profile": "specialist"}
    assert compare_reports(report("base"), mismatched)["decision"] == "DON'T SHIP"


def test_tiny_or_unhashed_artifact_is_not_qualified(tmp_path: Path) -> None:
    artifact = tmp_path / "adapter.safetensors"
    artifact.write_bytes(b"tiny")
    result = validate_model_artifact(artifact, expected_sha256=hashlib.sha256(b"tiny").hexdigest())
    assert result["qualified"] is False
    assert "small" in result["reason"] or "checkpoint" in result["reason"]


def test_training_manifest_validator_rejects_manifest_row_group_mismatch(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    manifest_path = tmp_path / "dataset.json"
    build_dataset(Path("tests/fixtures/canonical/incident.json"), generated, manifest_path=manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cases"][0]["entity_group_id"] = "different-entity"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = validate_dataset(generated, manifest_path)
    assert report["status"] == "invalid"
    assert any("manifest" in error or "group" in error for error in report["errors"])
