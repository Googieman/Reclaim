"""Tenant-scoped, read-only merchant evidence connector boundaries."""

from .allowlist import APPROVED_EVIDENCE_RESOURCES, validate_evidence_manifest
from .base import (
    EvidenceConnector,
    EvidenceConnectorError,
    EvidencePayloadLimitError,
    EvidenceReadResult,
    LiveEvidenceConnector,
    ReadOnlyEvidenceAdapter,
)

EvidenceConnectorAdapter = ReadOnlyEvidenceAdapter
ReadOnlyEvidenceConnector = ReadOnlyEvidenceAdapter

__all__ = [
    "APPROVED_EVIDENCE_RESOURCES",
    "EvidenceConnector",
    "EvidenceConnectorAdapter",
    "EvidenceConnectorError",
    "EvidencePayloadLimitError",
    "EvidenceReadResult",
    "LiveEvidenceConnector",
    "ReadOnlyEvidenceAdapter",
    "ReadOnlyEvidenceConnector",
    "validate_evidence_manifest",
]
