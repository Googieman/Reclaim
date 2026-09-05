"""T116 implementation-level sealed-store checks."""

import pytest

from evaluation.held_out_policy import HeldOutAccessError
from evaluation.sealed_store import SealedStore


def test_only_final_evaluation_capability_can_read_payload() -> None:
    store = SealedStore()
    reference = store.seal(
        {"secret_scenario": "must-not-leak"},
        case_identity="case-held-out",
        seed="held-out-seed",
        scenario="held-out-scenario",
    )
    assert "must-not-leak" not in repr(reference)
    with pytest.raises(HeldOutAccessError):
        store.read(reference, operation="model_selection")
    authorization = store.authorize_final_evaluation(
        evaluation_run_id="evaluation-run-final",
        reason="authorized final benchmark",
    )
    assert store.read(reference, authorization) == {"secret_scenario": "must-not-leak"}


def test_capability_from_another_store_cannot_read() -> None:
    first, second = SealedStore(), SealedStore()
    reference = first.seal({}, case_identity="case", seed="seed", scenario="scenario")
    authorization = second.authorize_final_evaluation(
        evaluation_run_id="run", reason="final evaluation"
    )
    with pytest.raises(HeldOutAccessError):
        first.read(reference, authorization)
