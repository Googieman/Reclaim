"""Validation and qualification gates for the RECLAIM evaluation manifest.

The manifest is metadata authority for evaluation boundaries.  A manifest can be
structurally valid while still being unsuitable for model selection; shortfalls
are reported as qualification failures instead of being repaired with padding.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .splitting import SPLITS, validate_split_order

MANIFEST_VERSION = "evaluation-manifest-v1.0.0"
MIN_HELD_OUT_CASES = 100
MIN_HELD_OUT_SAMPLE_COUNT = MIN_HELD_OUT_CASES
MIN_NO_COMPROMISE_FRACTION = 0.25
MIN_MIXED_COMPROMISED_FRACTION = 0.30


def validate_evaluation_manifest(
    manifest: Mapping[str, Any],
    *,
    min_held_out_cases: int = MIN_HELD_OUT_CASES,
    min_no_compromise_fraction: float = MIN_NO_COMPROMISE_FRACTION,
    min_mixed_compromised_fraction: float = MIN_MIXED_COMPROMISED_FRACTION,
) -> dict[str, Any]:
    """Validate manifest shape, split isolation, and non-fabrication gates.

    ``status`` describes structural validity.  ``qualification`` separately
    describes whether the observed corpus is large and balanced enough for model
    selection.  This distinction is important for an empty or undersized corpus:
    it is valid evidence of absence, never evidence of model quality.
    """

    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        return {
            "status": "invalid",
            "errors": ["evaluation manifest must be an object"],
            "qualification": _qualification(0, 0, 0, min_held_out_cases, min_no_compromise_fraction, min_mixed_compromised_fraction),
        }
    value = dict(manifest)
    _require_text(value, "manifest_version", errors, expected=MANIFEST_VERSION)
    for name in ("corpus_version", "environment_version"):
        _require_text(value, name, errors)
    cases = value.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        cases = []
    case_count = _nonnegative_int(value.get("case_count"), "case_count", errors)
    if case_count != len(cases):
        errors.append("case_count does not match cases")
    target_count = _positive_int(value.get("target_case_count"), "target_case_count", errors)

    split_metadata = value.get("split_metadata")
    if not isinstance(split_metadata, Mapping):
        errors.append("split_metadata must be an object")
        split_metadata = {}
    if split_metadata.get("assignments_frozen_before_overlay") is not True:
        errors.append("split assignments must be frozen before overlays")
    if split_metadata.get("held_out_sealed") is not True:
        errors.append("held-out inputs must be sealed")
    actual_counts = _split_counts(cases, errors)
    supplied_counts = split_metadata.get("actual_counts")
    if not isinstance(supplied_counts, Mapping):
        errors.append("split_metadata.actual_counts must be an object")
        supplied_counts = {}
    for split in SPLITS:
        if supplied_counts.get(split) != actual_counts[split]:
            errors.append(f"actual count mismatch for {split}")
    target_ratios = split_metadata.get("target_ratios")
    if not isinstance(target_ratios, Mapping) or set(target_ratios) != set(SPLITS):
        errors.append("target_ratios must define development, validation, and held_out")
    elif any(
        isinstance(target_ratios[split], bool)
        or not isinstance(target_ratios[split], (int, float))
        or not 0 <= float(target_ratios[split]) <= 1
        for split in SPLITS
    ) or abs(sum(float(target_ratios[split]) for split in SPLITS) - 1) > 1e-9:
        errors.append("target_ratios must be non-negative and sum to one")

    try:
        split_report = validate_split_order(cases)
    except (TypeError, ValueError) as exc:
        split_report = {"valid": False}
        errors.append(f"split validation failed: {exc}")
    _validate_cases(cases, errors)
    _validate_class_balance(value.get("class_balance"), errors)
    class_balance = value.get("class_balance") if isinstance(value.get("class_balance"), Mapping) else {}
    no_compromise = _count(class_balance, "no_compromise_false_alert", errors)
    mixed = _count(class_balance, "mixed_legitimate_malicious", errors)
    compromised = _count(class_balance, "malicious", errors)
    if mixed > compromised:
        errors.append("mixed legitimate/malicious count cannot exceed compromised count")
    if not isinstance(value.get("limitations"), list) or any(
        not isinstance(item, str) or not item.strip() for item in value.get("limitations", [])
    ):
        errors.append("limitations must be a list of non-empty strings")
    _validate_provenance_metadata(value, errors)

    qualification = _qualification(
        actual_counts["held_out"],
        no_compromise,
        mixed,
        min_held_out_cases,
        min_no_compromise_fraction,
        min_mixed_compromised_fraction,
        compromised_count=compromised,
        total_count=case_count,
    )
    limitations = list(value.get("limitations", [])) if isinstance(value.get("limitations"), list) else []
    limitations.extend(qualification["limitations"])
    if target_count and case_count < target_count:
        limitations.append(f"actual case count {case_count} is below target {target_count}; no cases are fabricated or padded")
    return {
        "status": "valid" if not errors else "invalid",
        "manifest_version": value.get("manifest_version"),
        "corpus_version": value.get("corpus_version"),
        "case_count": case_count,
        "split_counts": actual_counts,
        "split_validation": split_report,
        "qualification": qualification,
        "errors": errors,
        "limitations": list(dict.fromkeys(limitations)),
    }


def require_qualified_manifest(
    manifest: Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Raise unless a valid, sufficiently composed manifest is model-selection ready."""

    report = validate_evaluation_manifest(manifest, **kwargs)
    if report["status"] != "valid":
        raise ValueError("evaluation manifest is invalid: " + "; ".join(report["errors"]))
    if not report["qualification"]["ready_for_model_selection"]:
        raise ValueError(
            "evaluation manifest is not qualified: "
            + "; ".join(report["qualification"]["limitations"])
        )
    return report


validate_manifest = validate_evaluation_manifest
qualify_manifest = require_qualified_manifest


def _qualification(
    held_out_count: int,
    no_compromise: int,
    mixed: int,
    min_held_out: int,
    min_no_compromise: float,
    min_mixed: float,
    *,
    compromised_count: int = 0,
    total_count: int = 0,
) -> dict[str, Any]:
    held_out_ok = held_out_count >= min_held_out
    no_compromise_ratio = no_compromise / total_count if total_count else 0.0
    mixed_ratio = mixed / compromised_count if compromised_count else 0.0
    no_compromise_ok = total_count > 0 and no_compromise_ratio >= min_no_compromise
    mixed_ok = compromised_count > 0 and mixed_ratio >= min_mixed
    limitations = []
    if not held_out_ok:
        limitations.append(f"held-out count {held_out_count} is below minimum {min_held_out}")
    if not no_compromise_ok:
        limitations.append(f"no-compromise/false-alert composition {no_compromise_ratio:.3f} is below minimum {min_no_compromise:.3f}")
    if not mixed_ok:
        limitations.append(f"mixed legitimate/malicious composition {mixed_ratio:.3f} is below minimum {min_mixed:.3f}")
    return {
        "held_out_minimum": held_out_ok,
        "held_out_count": held_out_count,
        "minimum_held_out_count": min_held_out,
        "no_compromise_composition": no_compromise_ok,
        "no_compromise_false_alert_count": no_compromise,
        "no_compromise_fraction": round(no_compromise_ratio, 6),
        "mixed_legitimate_malicious_composition": mixed_ok,
        "mixed_legitimate_malicious_count": mixed,
        "mixed_legitimate_malicious_fraction_of_compromised": round(mixed_ratio, 6),
        "ready_for_model_selection": held_out_ok and no_compromise_ok and mixed_ok,
        "limitations": limitations,
    }


def _validate_cases(cases: list[Any], errors: list[str]) -> None:
    allowed = {"evaluation_case_id", "provenance", "split", "entity_group_id", "customer_group_id", "temporal_boundary", "sealed", "content_checksum"}
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            errors.append(f"case {index} must be an object")
            continue
        unknown = set(case) - allowed
        if unknown:
            errors.append(f"case {index} contains unsupported fields: {sorted(unknown)}")
        if case.get("split") == "held_out":
            if case.get("sealed") is not True:
                errors.append(f"held-out case {index} is not sealed")
            checksum = case.get("content_checksum")
            if not isinstance(checksum, str) or len(checksum) != 64:
                errors.append(f"held-out case {index} requires a content checksum")
        elif "sealed" in case or "content_checksum" in case:
            errors.append(f"non-held-out case {index} contains held-out seal metadata")


def _validate_provenance_metadata(value: Mapping[str, Any], errors: list[str]) -> None:
    categories = value.get("provenance_categories")
    allowed = {"REAL_DISTRIBUTION", "RAZORPAY_TEST", "SYNTHETIC_OVERLAY"}
    if not isinstance(categories, list) or not categories or any(item not in allowed for item in categories):
        errors.append("provenance_categories must contain at least one allowed category")
    source = value.get("source_dataset")
    if not isinstance(source, Mapping) or not isinstance(source.get("source_references"), list):
        errors.append("source_dataset provenance is incomplete")
    overlay = value.get("synthetic_overlay")
    if not isinstance(overlay, Mapping) or overlay.get("generated_after_split") is not True:
        errors.append("synthetic overlays must be marked as generated after split")
    seed = value.get("seed_version")
    if not isinstance(seed, Mapping) or not _is_text(seed.get("seed")) or not _is_text(seed.get("version")):
        errors.append("seed_version provenance is incomplete")


def _validate_class_balance(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("class_balance must be an object")
        return
    for key, item in value.items():
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            errors.append(f"class_balance.{key} must be a non-negative integer")


def _split_counts(cases: list[Any], errors: list[str]) -> dict[str, int]:
    counts = {split: 0 for split in SPLITS}
    ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            continue
        case_id = case.get("evaluation_case_id")
        if not _is_text(case_id):
            errors.append(f"case {index} requires evaluation_case_id")
        elif case_id in ids:
            errors.append(f"duplicate evaluation_case_id: {case_id}")
        else:
            ids.add(case_id)
        split = case.get("split")
        if split not in SPLITS:
            errors.append(f"case {index} has an invalid split")
        else:
            counts[split] += 1
    return counts


def _require_text(value: Mapping[str, Any], name: str, errors: list[str], *, expected: str | None = None) -> None:
    if not _is_text(value.get(name)):
        errors.append(f"{name} is required")
    elif expected is not None and value[name] != expected:
        errors.append(f"{name} must be {expected}")


def _count(value: Mapping[str, Any], name: str, errors: list[str]) -> int:
    item = value.get(name, 0)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        errors.append(f"class_balance.{name} must be a non-negative integer")
        return 0
    return item


def _nonnegative_int(value: Any, name: str, errors: list[str]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"{name} must be a non-negative integer")
        return 0
    return value


def _positive_int(value: Any, name: str, errors: list[str]) -> int:
    result = _nonnegative_int(value, name, errors)
    if result == 0 and not errors[-1].startswith(name):
        errors.append(f"{name} must be positive")
    return result


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "MANIFEST_VERSION",
    "MIN_HELD_OUT_CASES",
    "MIN_HELD_OUT_SAMPLE_COUNT",
    "MIN_MIXED_COMPROMISED_FRACTION",
    "MIN_NO_COMPROMISE_FRACTION",
    "require_qualified_manifest",
    "qualify_manifest",
    "validate_manifest",
    "validate_evaluation_manifest",
]
