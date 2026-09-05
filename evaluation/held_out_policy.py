"""Policy boundary for sealed held-out evaluation inputs."""

from __future__ import annotations

from dataclasses import dataclass

SEALED_SPLIT = "held_out"
FINAL_EVALUATION_OPERATION = "final_evaluation"
FORBIDDEN_OPERATIONS = frozenset(
    {
        "prompt",
        "model_selection",
        "hyperparameter_tuning",
        "lightgbm_tuning",
        "policy_tuning",
        "developer_evaluation",
        "replay_debugging",
        "ui_demo",
    }
)


class HeldOutAccessError(PermissionError):
    """Raised when a non-final-evaluation path requests sealed data."""


@dataclass(frozen=True, slots=True)
class FinalEvaluationAuthorization:
    """Opaque capability issued by a :class:`SealedStore` for one run."""

    evaluation_run_id: str
    reason: str
    _capability: object

    def __repr__(self) -> str:
        return (
            "FinalEvaluationAuthorization("
            f"evaluation_run_id={self.evaluation_run_id!r}, reason={self.reason!r})"
        )


def require_final_evaluation_access(
    authorization: FinalEvaluationAuthorization | None,
    *,
    operation: str = FINAL_EVALUATION_OPERATION,
) -> FinalEvaluationAuthorization:
    """Require the explicit authorization capability for held-out reads."""

    if operation in FORBIDDEN_OPERATIONS or operation != FINAL_EVALUATION_OPERATION:
        raise HeldOutAccessError(
            f"held-out inputs are sealed from {operation or 'this operation'}"
        )
    if not isinstance(authorization, FinalEvaluationAuthorization):
        raise HeldOutAccessError("final evaluation authorization is required")
    if not authorization.evaluation_run_id.strip() or not authorization.reason.strip():
        raise HeldOutAccessError("final evaluation authorization is incomplete")
    return authorization


class HeldOutPolicy:
    """Small explicit policy object shared by stores and evaluation runners."""

    def require(
        self,
        authorization: FinalEvaluationAuthorization | None,
        *,
        operation: str = FINAL_EVALUATION_OPERATION,
    ) -> FinalEvaluationAuthorization:
        return require_final_evaluation_access(authorization, operation=operation)

    def can_read(self, authorization: FinalEvaluationAuthorization | None) -> bool:
        try:
            self.require(authorization)
        except HeldOutAccessError:
            return False
        return True


__all__ = [
    "FINAL_EVALUATION_OPERATION",
    "FORBIDDEN_OPERATIONS",
    "FinalEvaluationAuthorization",
    "HeldOutAccessError",
    "HeldOutPolicy",
    "SEALED_SPLIT",
    "require_final_evaluation_access",
]
