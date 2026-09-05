"""T105 canonical replay determinism boundary.

The runner and canonical fixture are deliberately future seams owned by T111 and
T112.  This test defines the comparison that must become green when those tasks
are implemented; it does not provide a runner or fixture fallback.
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


CANONICAL_INPUT = {
    "fixture_version": "canonical-v1.0.0",
    "tenant_id": "tenant-t105",
    "case_id": "case-t105",
    "policy_version_id": "policy-v1.0.0",
    "model_provider_mode": "replay-fixture/provider-v1.0.0",
    "deterministic_seed": 105,
    "environment_metadata": {"provider_available": False, "executor": "pytest"},
    "events": (
        {"event_id": "event-2", "occurred_at": "2026-09-01T12:01:00Z"},
        {"event_id": "event-1", "occurred_at": "2026-09-01T12:00:00Z"},
        {"event_id": "event-1", "occurred_at": "2026-09-01T12:00:00Z"},
    ),
}


def test_canonical_replay_repeats_identical_authoritative_outputs() -> None:
    run_replay = _require_symbol("replay.runner", "run_replay", task="T111")

    first = run_replay(**CANONICAL_INPUT)
    second = run_replay(**CANONICAL_INPUT)

    assert first == second
    assert first["mode"] == "replay"
    assert first["label"] == "replay"
    assert first["timeline"] == second["timeline"]
    assert first["exposure"] == second["exposure"]
    assert first["policy_decision"] == second["policy_decision"]
    assert first["proposal_validation"] == second["proposal_validation"]
    assert first["terminal_state"] == second["terminal_state"]
    assert first["audit"] == second["audit"]
