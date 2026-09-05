"""Opaque in-process sealed storage for held-out seeds and scenarios.

The store deliberately keeps payloads in a private capability-gated map. A
reference contains checksum and split metadata only, never the held-out
plaintext. The final evaluation path receives the only read capability; all
tuning, prompt, replay-debugging, and UI callers fail closed.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

from .held_out_policy import (
    FINAL_EVALUATION_OPERATION,
    FinalEvaluationAuthorization,
    HeldOutAccessError,
    HeldOutPolicy,
    SEALED_SPLIT,
)

SEALED_STORE_VERSION = "sealed-store-v1.0.0"


@dataclass(frozen=True, slots=True)
class SealedReference:
    reference_id: str
    split: str
    version: str
    checksum: str
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.split != SEALED_SPLIT:
            raise ValueError("only held-out inputs may be stored in the sealed store")
        if len(self.checksum) != 64:
            raise ValueError("sealed payload checksum is malformed")
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))


class SealedStore:
    """Capability-gated store whose public references omit payload contents."""

    def __init__(self, *, policy: HeldOutPolicy | None = None) -> None:
        self.policy = policy or HeldOutPolicy()
        self._payloads: dict[str, bytes] = {}
        self._capabilities: dict[str, object] = {}
        self._store_capability = object()
        self._authorizations: list[dict[str, str]] = []

    def seal(
        self,
        payload: Any,
        *,
        split: str = SEALED_SPLIT,
        version: str = SEALED_STORE_VERSION,
        case_identity: str,
        seed: str,
        scenario: str,
        provenance: str = "sealed-held-out",
    ) -> SealedReference:
        if split != SEALED_SPLIT:
            raise ValueError("sealed store accepts only held_out inputs")
        for name, value in (
            ("case_identity", case_identity),
            ("seed", seed),
            ("scenario", scenario),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"sealed {name} is required")
        encoded = _encode(payload)
        checksum = hashlib.sha256(encoded).hexdigest()
        reference_id = "sealed:" + secrets.token_hex(16)
        self._payloads[reference_id] = encoded
        self._capabilities[reference_id] = self._store_capability
        return SealedReference(
            reference_id=reference_id,
            split=split,
            version=version,
            checksum=checksum,
            metadata={
                "case_identity": case_identity,
                "seed_checksum": hashlib.sha256(seed.encode()).hexdigest(),
                "scenario_checksum": hashlib.sha256(scenario.encode()).hexdigest(),
                "provenance": provenance,
                "sealed": True,
            },
        )

    def authorize_final_evaluation(
        self,
        *,
        evaluation_run_id: str,
        reason: str,
    ) -> FinalEvaluationAuthorization:
        if not evaluation_run_id.strip() or not reason.strip():
            raise HeldOutAccessError(
                "evaluation authorization requires run identity and reason"
            )
        authorization = FinalEvaluationAuthorization(
            evaluation_run_id, reason, self._store_capability
        )
        self._authorizations.append(
            {
                "evaluation_run_id": evaluation_run_id,
                "reason": reason,
                "operation": FINAL_EVALUATION_OPERATION,
            }
        )
        return authorization

    def read(
        self,
        reference: SealedReference,
        authorization: FinalEvaluationAuthorization | None = None,
        *,
        operation: str = FINAL_EVALUATION_OPERATION,
    ) -> Any:
        if not isinstance(reference, SealedReference):
            raise HeldOutAccessError("a sealed reference is required")
        authorized = self.policy.require(authorization, operation=operation)
        expected_capability = self._capabilities.get(reference.reference_id)
        # An authorization issued by another store cannot read this store. The
        # opaque object identity is the boundary; no string or naming convention
        # can substitute for it.
        if expected_capability is None or not _authorization_belongs_to_store(
            authorized, self._capabilities, reference.reference_id
        ):
            raise HeldOutAccessError(
                "held-out reference is not authorized for this store"
            )
        encoded = self._payloads.get(reference.reference_id)
        if encoded is None or hashlib.sha256(encoded).hexdigest() != reference.checksum:
            raise HeldOutAccessError(
                "sealed held-out payload is unavailable or corrupt"
            )
        return json.loads(encoded.decode("utf-8"))

    def metadata(self, reference: SealedReference) -> dict[str, Any]:
        if not isinstance(reference, SealedReference):
            raise HeldOutAccessError("a sealed reference is required")
        return dict(reference.metadata)

    @property
    def authorization_log(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(value) for value in self._authorizations)


def _authorization_belongs_to_store(
    authorization: FinalEvaluationAuthorization,
    capabilities: dict[str, object],
    reference_id: str,
) -> bool:
    # The returned authorization carries a private capability object. It is
    # intentionally not serialized into metadata or exposed by repr.
    return authorization._capability is capabilities.get(reference_id)


def _encode(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("sealed metadata must be an object")
    return {
        key: item
        for key, item in value.items()
        if key not in {"payload", "plaintext", "seed", "scenario", "inputs"}
    }


__all__ = ["SEALED_STORE_VERSION", "SealedReference", "SealedStore"]
