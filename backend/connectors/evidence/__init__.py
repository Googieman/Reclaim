"""Tenant-scoped, read-only merchant evidence connector boundaries."""

from .allowlist import APPROVED_EVIDENCE_RESOURCES, validate_evidence_manifest
from .base import (
    EvidenceConnector,
    EvidenceConnectorError,
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
    "EvidenceReadResult",
    "LiveEvidenceConnector",
    "ReadOnlyEvidenceAdapter",
    "ReadOnlyEvidenceConnector",
    "validate_evidence_manifest",
]
