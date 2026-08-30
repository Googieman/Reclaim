"""Named adapter exports for live and deterministic evidence connectors."""

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
    "EvidenceConnector",
    "EvidenceConnectorAdapter",
    "EvidenceConnectorError",
    "EvidencePayloadLimitError",
    "EvidenceReadResult",
    "LiveEvidenceConnector",
    "ReadOnlyEvidenceAdapter",
    "ReadOnlyEvidenceConnector",
]
