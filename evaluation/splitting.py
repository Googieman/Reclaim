"""Grouped and temporal dataset splitting with overlay-order enforcement."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

SPLIT_VERSION = "evaluation-splitting-v1.0.0"
SPLITS = ("development", "validation", "held_out")


def validate_split_order(
    cases: Sequence[Mapping[str, Any] | object],
    *,
    held_out_access: str = "sealed",
) -> dict[str, Any]:
    """Validate frozen assignments and fail closed on any leakage signal."""

    normalized = [_case_values(value, index=index) for index, value in enumerate(cases)]
    ids = [value["evaluation_case_id"] for value in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("evaluation case identities must be unique")
    grouping: dict[str, dict[str, str]] = defaultdict(dict)
    for value in normalized:
        split = value["split"]
        for kind in ("entity_group_id", "customer_group_id"):
            group = value.get(kind)
            if group is None:
                continue
            previous = grouping[kind].get(group)
            if previous is not None and previous != split:
                raise ValueError(f"{kind} leakage crosses evaluation splits")
            grouping[kind][group] = split
        lineage = value.get("synthetic_overlay_lineage")
        if isinstance(lineage, str) and any(
            marker in lineage.lower()
            for marker in ("before_split", "pre_split", "global")
        ):
            raise ValueError(
                "synthetic overlays must be generated after split assignments freeze"
            )
    boundaries = {
        split: [
            value["temporal_boundary"]
            for value in normalized
            if value["split"] == split
        ]
        for split in SPLITS
    }
    for earlier, later in zip(SPLITS, SPLITS[1:]):
        if (
            boundaries[earlier]
            and boundaries[later]
            and max(boundaries[earlier]) > min(boundaries[later])
        ):
            raise ValueError(
                "temporal leakage permits future cases in an earlier split"
            )
    if held_out_access not in {"sealed", "final_evaluation"}:
        raise ValueError("held-out inputs are sealed from tuning and model selection")
    total = len(normalized)
    counts = {
        split: sum(value["split"] == split for value in normalized) for split in SPLITS
    }
    ratios = {
        split: round(counts[split] / total, 10) if total else 0.0 for split in SPLITS
    }
    return {
        "valid": True,
        "split_counts": counts,
        "ratios": ratios,
        "target_ratios": {"development": 0.6, "validation": 0.2, "held_out": 0.2},
        "grouping_checks": {"entity": True, "customer": True},
        "temporal_separation": True,
        "synthetic_overlay_applied_after_split": True,
        "assignments_frozen": True,
        "held_out_access_policy": "sealed",
        "held_out_access": held_out_access,
        "provenance": {
            "algorithm_version": SPLIT_VERSION,
            "order": "raw/source cases -> grouped/temporal split -> freeze -> overlays",
            "case_count": total,
        },
    }


def split_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    seed: str = "fs001-evaluation-seed-v1",
    version: str = SPLIT_VERSION,
    ratios: Mapping[str, float] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Assign raw cases deterministically, keeping entity/customer groups intact."""

    if version != SPLIT_VERSION:
        raise ValueError(f"unsupported splitting version: {version}")
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("split seed is required")
    values = [
        _case_values(value, index=index, require_split=False)
        for index, value in enumerate(cases)
    ]
    if not values:
        return ()
    if all(value.get("split") in SPLITS for value in values):
        validate_split_order(values)
        return tuple(_stable_copy(value) for value in values)
    target = dict(ratios or {"development": 0.6, "validation": 0.2, "held_out": 0.2})
    if (
        set(target) != set(SPLITS)
        or abs(sum(float(value) for value in target.values()) - 1) > 1e-9
    ):
        raise ValueError(
            "split ratios must define development, validation, and held_out"
        )
    components = _group_components(values, seed=seed)
    desired = _desired_counts(len(values), target)
    assigned: dict[str, str] = {}
    counts = {split: 0 for split in SPLITS}
    ordered_components = sorted(
        components,
        key=lambda group: (
            min(values[index]["temporal_boundary"] for index in group),
            group[0],
        ),
    )
    for component in ordered_components:
        split = next(
            (
                candidate
                for candidate in SPLITS
                if counts[candidate] + len(component) <= desired[candidate]
            ),
            min(
                SPLITS,
                key=lambda candidate: (
                    counts[candidate] / max(desired[candidate], 1),
                    candidate,
                ),
            ),
        )
        for index in component:
            assigned[values[index]["evaluation_case_id"]] = split
        counts[split] += len(component)
    result = []
    for value in values:
        item = _stable_copy(value)
        item["split"] = assigned[value["evaluation_case_id"]]
        item["split_provenance"] = {
            "algorithm_version": version,
            "seed": seed,
            "assignments_frozen_before_overlay": True,
        }
        result.append(item)
    validate_split_order(result)
    return tuple(result)


def apply_synthetic_overlays(
    split_cases_result: Sequence[Mapping[str, Any]],
    overlay_factory: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
    *,
    overlay_version: str = "synthetic-overlay-v1.0.0",
) -> tuple[dict[str, Any], ...]:
    """Generate overlays only inside an already validated, frozen split."""

    frozen = tuple(_stable_copy(value) for value in split_cases_result)
    validate_split_order(frozen)
    result = []
    for value in frozen:
        overlay = overlay_factory(dict(value), overlay_version)
        if not isinstance(overlay, Mapping):
            raise ValueError("synthetic overlay factory must return an object")
        item = dict(value)
        item.update(_stable_copy(overlay))
        item["split"] = value["split"]
        item["synthetic_overlay_lineage"] = (
            f"{overlay_version}:after-split:{value['split']}"
        )
        result.append(item)
    validate_split_order(result)
    return tuple(result)


generate_synthetic_overlays = apply_synthetic_overlays


def _group_components(
    values: Sequence[Mapping[str, Any]], *, seed: str
) -> list[list[int]]:
    parent = list(range(len(values)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owners: dict[tuple[str, str], int] = {}
    for index, value in enumerate(values):
        for kind in ("entity_group_id", "customer_group_id"):
            group = value.get(kind)
            if group is not None:
                key = (kind, str(group))
                if key in owners:
                    union(index, owners[key])
                else:
                    owners[key] = index
    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(len(values)):
        grouped[find(index)].append(index)
    return sorted(
        grouped.values(),
        key=lambda component: hashlib.sha256(
            f"{seed}:{','.join(values[index]['evaluation_case_id'] for index in component)}".encode()
        ).hexdigest(),
    )


def _desired_counts(total: int, ratios: Mapping[str, float]) -> dict[str, int]:
    raw = {split: total * float(ratios[split]) for split in SPLITS}
    counts = {split: int(raw[split]) for split in SPLITS}
    for split in sorted(
        SPLITS, key=lambda item: raw[item] - counts[item], reverse=True
    ):
        if sum(counts.values()) < total:
            counts[split] += 1
    return counts


def _case_values(
    value: Mapping[str, Any] | object,
    *,
    index: int,
    require_split: bool = True,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        raw = dict(value)
    elif hasattr(value, "model_dump"):
        raw = dict(value.model_dump(mode="python"))
    else:
        raw = {
            name: getattr(value, name, None)
            for name in (
                "evaluation_case_id",
                "split",
                "entity_group_id",
                "customer_group_id",
                "temporal_boundary",
                "synthetic_overlay_lineage",
            )
        }
    case_id = raw.get("evaluation_case_id")
    entity = raw.get("entity_group_id")
    split = raw.get("split")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"evaluation case {index} identity is required")
    if not isinstance(entity, str) or not entity.strip():
        raise ValueError(f"evaluation case {index} entity group is required")
    if require_split and split not in SPLITS:
        raise ValueError(f"evaluation case {case_id} has an invalid split")
    if split is not None and split not in SPLITS:
        raise ValueError(f"evaluation case {case_id} has an invalid split")
    moment = raw.get("temporal_boundary")
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if (
        not isinstance(moment, datetime)
        or moment.tzinfo is None
        or moment.utcoffset() is None
    ):
        raise ValueError(
            f"evaluation case {case_id} requires a timezone-aware temporal boundary"
        )
    output = dict(raw)
    output.update(
        {
            "evaluation_case_id": case_id.strip(),
            "entity_group_id": entity.strip(),
            "customer_group_id": (
                None
                if raw.get("customer_group_id") is None
                else str(raw["customer_group_id"]).strip()
            ),
            "temporal_boundary": moment.astimezone(UTC),
        }
    )
    return output


def _stable_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            value,
            sort_keys=True,
            default=lambda item: item.isoformat()
            if isinstance(item, datetime)
            else str(item),
        )
    )


__all__ = [
    "SPLIT_VERSION",
    "SPLITS",
    "apply_synthetic_overlays",
    "generate_synthetic_overlays",
    "split_cases",
    "validate_split_order",
]
