"""Defense-only model capability and untrusted-evidence boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.observability.redaction import redact


class CapabilityViolation(PermissionError):
    """Raised when an agent asks for a capability outside its typed boundary."""


class AllowedCapability(StrEnum):
    READ_CASE = "read_case"
    READ_EVIDENCE = "read_evidence"
    PROPOSE_ACTION = "propose_action"


FORBIDDEN_CAPABILITIES = frozenset(
    {
        "database_write",
        "execute_payment",
        "execute_refund",
        "shell_command",
        "arbitrary_network",
        "credential_probe",
    }
)


class BoundedToolSet:
    def __init__(self, capabilities: set[AllowedCapability] | frozenset[AllowedCapability]) -> None:
        self.capabilities = frozenset(capabilities)

    def require(self, capability: str | AllowedCapability) -> None:
        name = str(capability)
        if name in FORBIDDEN_CAPABILITIES or name not in {item.value for item in self.capabilities}:
            raise CapabilityViolation(f"capability is not available to the model: {name}")

    def names(self) -> frozenset[str]:
        return frozenset(item.value for item in self.capabilities)


@dataclass(frozen=True, slots=True)
class UntrustedEvidence:
    evidence_id: str
    content: Mapping[str, Any]
    checksum: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")

    def redacted_content(self) -> dict[str, Any]:
        return dict(redact(self.content))
