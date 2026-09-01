"""T107 grouped, temporal, and sealed-split evaluation boundaries."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import pytest


def _require_symbol(module_name: str, symbol_name: str, *, task: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "unknown module"
        if missing_name == module_name or module_name.startswith(f"{missing_name}."):
            raise AssertionError(
                f"{task} production seam is not implemented: {module_name}.{symbol_name}"
            ) from exc
        raise
    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        raise AssertionError(
            f"{task} production seam is missing: {module_name}.{symbol_name}"
        ) from exc


def _case(
    case_id: str,
    *,
    split: str,
    month: int,
    entity: str | None = None,
    customer: str | None = None,
) -> dict[str, Any]:
    return {
        "evaluation_case_id": case_id,
        "split": split,
        "entity_group_id": entity or f"entity-{case_id}",
        "customer_group_id": customer or f"customer-{case_id}",
        "temporal_boundary": datetime(2026, month, 1, tzinfo=UTC),
        "synthetic_overlay_lineage": None,
        "seed": f"{split}-seed-{case_id}",
        "scenario": f"{split}-scenario-{case_id}",
    }


VALID_CASES = (
    _case("dev-1", split="development", month=1),
    _case("dev-2", split="development", month=1),
    _case("dev-3", split="development", month=1),
    _case("dev-4", split="development", month=1),
    _case("dev-5", split="development", month=1),
    _case("dev-6", split="development", month=1),
    _case("validation-1", split="validation", month=2),
    _case("validation-2", split="validation", month=2),
    _case("held-out-1", split="held_out", month=3),
    _case("held-out-2", split="held_out", month=3),
)


@pytest.mark.xfail(
    strict=True,
    reason="T107 is expected-red until T114/T115 split validation is implemented",
)
def test_split_validation_is_grouped_temporal_and_overlay_ordered() -> None:
    validate_split_order = _require_symbol(
        "evaluation.splitting", "validate_split_order", task="T115"
    )

    result = validate_split_order(VALID_CASES)

    assert result["valid"] is True
    assert result["split_counts"] == {
        "development": 6,
        "validation": 2,
        "held_out": 2,
    }
    assert result["ratios"] == {
        "development": 0.6,
        "validation": 0.2,
        "held_out": 0.2,
    }
    assert result["grouping_checks"] == {"entity": True, "customer": True}
    assert result["temporal_separation"] is True
    assert result["synthetic_overlay_applied_after_split"] is True
    assert result["held_out_access_policy"] == "sealed"


@pytest.mark.xfail(
    strict=True,
    reason="T107 is expected-red until T115/T116 reject leakage and holdout access",
)
def test_split_validation_rejects_cross_group_leakage_and_holdout_access() -> None:
    validate_split_order = _require_symbol(
        "evaluation.splitting", "validate_split_order", task="T115"
    )
    leaked_cases = VALID_CASES + (
        _case(
            "leaked-validation",
            split="validation",
            month=2,
            entity="entity-dev-1",
            customer="customer-dev-1",
        ),
    )

    with pytest.raises(ValueError, match="leak|group|temporal"):
        validate_split_order(leaked_cases, held_out_access="model_selection")
