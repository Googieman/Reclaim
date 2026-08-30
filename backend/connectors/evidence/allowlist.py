"""The closed allowlist for merchant-controlled evidence reads."""

from __future__ import annotations

from app.contracts.registry import (
    ALLOWED_EVIDENCE_OPERATIONS,
    ALLOWED_EVIDENCE_RESOURCES,
    ContractCompatibilityError,
    validate_manifest,
)
from packages.contracts.connectors import ConnectorManifest, ConnectorType, EvidenceRequest

APPROVED_EVIDENCE_RESOURCES = frozenset(ALLOWED_EVIDENCE_RESOURCES)
APPROVED_EVIDENCE_OPERATIONS = frozenset(ALLOWED_EVIDENCE_OPERATIONS)


def validate_evidence_manifest(manifest: ConnectorManifest) -> ConnectorManifest:
    """Validate a manifest and restrict it to the evidence read boundary."""

    validate_manifest(manifest)
    if manifest.connector_type is not ConnectorType.EVIDENCE:
        raise ContractCompatibilityError("evidence adapter requires an evidence manifest")
    if not set(manifest.resources).issubset(APPROVED_EVIDENCE_RESOURCES):
        raise ContractCompatibilityError("evidence resource is not allowlisted")
    if not set(manifest.operations).issubset(APPROVED_EVIDENCE_OPERATIONS):
        raise ContractCompatibilityError("evidence operation is not read-only")
    return manifest


def validate_evidence_request(
    manifest: ConnectorManifest,
    request: EvidenceRequest,
) -> None:
    """Validate request identity and bounded read scope against a manifest."""

    if request.connector_id != manifest.connector_id:
        raise ContractCompatibilityError("evidence request connector does not match manifest")
    if request.resource_type not in manifest.resources:
        raise ContractCompatibilityError("evidence request resource is not allowlisted")
    if request.operation not in manifest.operations or request.operation != "read":
        raise ContractCompatibilityError("evidence request operation is not read-only")
    if request.page_size > manifest.limits.max_page_size:
        raise ContractCompatibilityError("evidence request exceeds connector page limit")
