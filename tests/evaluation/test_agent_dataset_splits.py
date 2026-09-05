"""Leakage and held-out sealing checks for the feature-local dataset manifest."""

from __future__ import annotations

import pytest

from evaluation.splitting import validate_split_order
from training.reclaim.scripts.splits import validate_frozen_splits


def case(
    case_id: str, split: str, boundary: str, entity: str = "entity"
) -> dict[str, str]:
    return {
        "evaluation_case_id": case_id,
        "split": split,
        "entity_group_id": entity,
        "customer_group_id": f"customer-{case_id}",
        "temporal_boundary": boundary,
    }


def test_group_and_temporal_leakage_are_rejected() -> None:
    with pytest.raises(ValueError, match="entity_group"):
        validate_split_order(
            [
                case("a", "development", "2026-01-01T00:00:00+00:00"),
                case("b", "validation", "2026-02-01T00:00:00+00:00"),
            ]
        )
    with pytest.raises(ValueError, match="temporal"):
        validate_split_order(
            [
                case("a", "development", "2026-03-01T00:00:00+00:00", "entity-a"),
                case("b", "validation", "2026-02-01T00:00:00+00:00", "entity-b"),
            ]
        )


def test_frozen_manifest_requires_sealed_held_out_metadata() -> None:
    with pytest.raises(ValueError, match="sealed"):
        validate_frozen_splits({"held_out_sealed": False, "cases": []})
