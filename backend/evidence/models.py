"""Immutable runtime values exchanged by evidence and timeline services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packages.contracts.connectors import EvidenceResponse


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    """Source and replay metadata attached to a collected evidence item."""

    tenant_id: str
    case_id: str
    correlation_id: str
    connector_id: str
    resource_type: str
    source_identity: str
    mode: str
    source: str
    version: str
    seed: str
    evidence_id: str
    raw_checksum: str
    original_timestamps: Mapping[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.tenant_id,
                self.case_id,
                self.correlation_id,
                self.connector_id,
                self.resource_type,
                self.source_identity,
                self.mode,
                self.source,
                self.version,
                self.seed,
                self.evidence_id,
                self.raw_checksum,
            )
        ):
            raise ValueError("evidence provenance fields are required")
        object.__setattr__(self, "original_timestamps", dict(self.original_timestamps))


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    """A deterministic, provenance-linked fact suitable for timeline reconstruction."""

    tenant_id: str
    case_id: str
    evidence_id: str
    resource_type: str
    source_identity: str
    source_event_id: str
    canonical_event_type: str
    dedupe_key: str
    effective_at: datetime
    observed_at: datetime
    received_at: datetime
    event_at: datetime | None
    source_priority: int
    payload: Mapping[str, Any]
    provider_identifiers: Mapping[str, str] = field(default_factory=dict)
    original_timestamps: Mapping[str, str | None] = field(default_factory=dict)
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "case_id",
            "evidence_id",
            "resource_type",
            "source_identity",
            "source_event_id",
            "canonical_event_type",
            "dedupe_key",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"normalized fact {name} is required")
        if self.source_priority < 0:
            raise ValueError("normalized fact source priority cannot be negative")
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "provider_identifiers", dict(self.provider_identifiers))
        object.__setattr__(self, "original_timestamps", dict(self.original_timestamps))
        object.__setattr__(
            self,
            "evidence_references",
            tuple(sorted(set(self.evidence_references))),
        )


@dataclass(frozen=True, slots=True)
class CollectedEvidence:
    """One immutable connector response after raw storage and normalization."""

    tenant_id: str
    case_id: str
    correlation_id: str
    evidence_id: str
    connector_id: str
    resource_type: str
    source_identifier: str
    source_identity: str
    observed_at: datetime
    received_at: datetime
    raw_object_uri: str | None
    raw_checksum: str
    expected_checksum: str
    completeness: str
    normalization_status: str
    integrity_status: str
    trust_classification: str = "untrusted"
    collection_error: str | None = None
    normalized_facts: tuple[NormalizedFact, ...] = ()
    provenance: EvidenceProvenance | None = None
    response: EvidenceResponse | None = None

    @property
    def untrusted(self) -> bool:
        return self.trust_classification == "untrusted"

    @property
    def raw_artifact_reference(self) -> str | None:
        return self.raw_object_uri


@dataclass(frozen=True, slots=True)
class EvidenceCollectionResult:
    """Deterministic collection output; missing sources are represented as items."""

    tenant_id: str
    case_id: str
    correlation_id: str
    items: tuple[CollectedEvidence, ...]
    normalized_facts: tuple[NormalizedFact, ...]
    provenance: tuple[EvidenceProvenance, ...]
    authoritative_store: str = "postgresql"
    raw_store: str = "minio"
    uncertainty: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "normalized_facts", tuple(self.normalized_facts))
        object.__setattr__(self, "provenance", tuple(self.provenance))
        object.__setattr__(self, "uncertainty", tuple(sorted(set(self.uncertainty))))
