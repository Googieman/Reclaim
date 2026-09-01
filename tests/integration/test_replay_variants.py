"""T106 deterministic replay-variant boundary.

Variant execution belongs to T113.  The parametrized expectations remain strict
so each required failure/recovery path is visible instead of being silently
treated as a happy-path replay.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

pytestmark = pytest.mark.integration


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


VARIANTS = (
    ("invalid_signature", "quarantined"),
    ("duplicate_delivery", "duplicate"),
    ("out_of_order_events", "converged"),
    ("missing_evidence", "escalated_unresolved"),
    ("policy_denial", "denied"),
    ("approval_gating", "approval_required"),
    ("unknown_remote_result", "reconciled"),
    ("forbidden_proposal", "rejected"),
    ("verification_failure", "verified_failed"),
    ("escalation", "escalated_unresolved"),
    ("provider_unavailability", "replay"),
)


@pytest.mark.parametrize("variant, expected_outcome", VARIANTS)
@pytest.mark.xfail(
    strict=True,
    reason="T106 is expected-red until T113 implements the deterministic variants",
)
def test_required_variant_is_replay_labeled_and_side_effect_free(
    variant: str, expected_outcome: str
) -> None:
    run_variant = _require_symbol("replay.variants", "run_variant", task="T113")

    result = run_variant(
        variant=variant,
        fixture_version="canonical-v1.0.0",
        deterministic_seed=106,
        mode="replay",
    )

    assert result["variant"] == variant
    assert result["mode"] == "replay"
    assert result["label"] == "replay"
    assert result["outcome"] == expected_outcome
    assert result["remote_side_effects"] == ()
