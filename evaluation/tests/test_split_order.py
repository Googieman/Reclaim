"""T115 implementation-level split-order checks."""

from datetime import UTC, datetime

import pytest

from evaluation.splitting import apply_synthetic_overlays, validate_split_order


def _case(
    case_id: str, split: str, month: int, entity: str | None = None
) -> dict[str, object]:
    return {
        "evaluation_case_id": case_id,
        "split": split,
        "entity_group_id": entity or f"entity-{case_id}",
        "customer_group_id": f"customer-{case_id}",
        "temporal_boundary": datetime(2026, month, 1, tzinfo=UTC),
    }


def test_overlay_is_applied_inside_frozen_split() -> None:
    cases = (
        _case("dev", "development", 1),
        _case("val", "validation", 2),
        _case("hold", "held_out", 3),
    )
    result = apply_synthetic_overlays(
        cases, lambda value, version: {"overlay": version}
    )
    assert validate_split_order(result)["synthetic_overlay_applied_after_split"] is True
    assert all(
        str(item["synthetic_overlay_lineage"]).startswith(
            "synthetic-overlay-v1.0.0:after-split"
        )
        for item in result
    )


def test_group_overlap_fails_closed() -> None:
    with pytest.raises(ValueError, match="leakage"):
        validate_split_order(
            (
                _case("dev", "development", 1, "shared"),
                _case("hold", "held_out", 2, "shared"),
            )
        )
