"""Tenant-bound evidence collection orchestration with safe failure handling."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app.auth.oidc import TenantAuthorizationContext, TenantAuthorizationError
from app.db.unit_of_work import PostgresUnitOfWork
from app.storage.minio_evidence import ObjectIntegrityError, checksum_for_bytes
from connectors.evidence.base import EvidenceConnector, EvidenceConnectorError
from packages.contracts.connectors import (
    ConnectorFailureState,
    EvidenceRequest,
    EvidenceResponse,
)

from .models import (
    CollectedEvidence,
    EvidenceCollectionResult,
    EvidenceProvenance,
)
from .normalization import EvidenceNormalizationError, normalize_response
from .storage import EvidenceStorage

UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]


class EvidenceCollectionError(RuntimeError):
    """Raised when authoritative evidence metadata cannot be persisted safely."""


class EvidenceOrchestrator:
    """Collect approved evidence without granting connector or side-effect authority."""

    policy_authority = "postgresql"
    authoritative_store = "postgresql"
    raw_store = "minio"

    def __init__(
        self,
        connectors: Mapping[str, EvidenceConnector] | Iterable[EvidenceConnector],
        *,
        storage: EvidenceStorage | None = None,
        unit_of_work_factory: UnitOfWorkFactory | None = None,
    ) -> None:
        values = (
            connectors.items()
            if isinstance(connectors, Mapping)
            else ((connector.manifest.connector_id, connector) for connector in connectors)
        )
        self._connectors: dict[str, EvidenceConnector] = {}
        for connector_id, connector in values:
            manifest = connector.manifest
            if connector_id != manifest.connector_id:
                raise ValueError("evidence connector mapping identity does not match manifest")
            if manifest.connector_id in self._connectors:
                raise ValueError("duplicate evidence connector identity")
            self._connectors[manifest.connector_id] = connector
        self.storage = storage
        self.unit_of_work_factory = unit_of_work_factory

    def requests_for_case(
        self,
        *,
        tenant_id: str,
        case_id: str,
        correlation_id: str,
        requested_at: Any,
    ) -> tuple[EvidenceRequest, ...]:
        """Build bounded requests from configured connectors in stable order."""

        return tuple(
            EvidenceRequest(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                case_id=case_id,
                connector_id=connector_id,
                resource_type=connector.manifest.resources[0],
                requested_at=requested_at,
                page_size=min(100, connector.manifest.limits.max_page_size),
            )
            for connector_id, connector in sorted(self._connectors.items())
        )

    def collect(
        self,
        *,
        case_id: str,
        requests: Iterable[EvidenceRequest],
        authorization_context: TenantAuthorizationContext,
    ) -> EvidenceCollectionResult:
        """Collect, store, normalize, and persist evidence for one authorized tenant."""

        self._require_authorization(authorization_context)
        ordered_requests = tuple(sorted(requests, key=_request_sort_key))
        if not ordered_requests:
            raise ValueError("evidence collection requires at least one request")
        for request in ordered_requests:
            if request.case_id != case_id:
                raise ValueError("evidence request case does not match collection case")
            if request.tenant_id != authorization_context.tenant_id:
                raise TenantAuthorizationError("evidence request crosses tenant boundary")
        correlations = {request.correlation_id for request in ordered_requests}
        if len(correlations) != 1:
            raise ValueError("evidence collection requests must share one correlation identity")

        items: list[CollectedEvidence] = []
        seen_items: set[str] = set()
        for request in ordered_requests:
            item = self._collect_one(request, authorization_context=authorization_context)
            if item.evidence_id in seen_items:
                continue
            seen_items.add(item.evidence_id)
            items.append(item)

        items.sort(key=lambda item: (item.resource_type, item.connector_id, item.evidence_id))
        if self.unit_of_work_factory is not None:
            self._persist_metadata(items, authorization_context=authorization_context)

        facts = tuple(fact for item in items for fact in item.normalized_facts)
        facts = tuple(
            sorted(
                facts,
                key=lambda fact: (
                    fact.effective_at,
                    fact.canonical_event_type,
                    fact.source_identity,
                    fact.source_event_id,
                    fact.evidence_id,
                ),
            )
        )
        provenance = tuple(item.provenance for item in items if item.provenance is not None)
        uncertainty = tuple(
            f"{item.connector_id}:{item.collection_error}"
            for item in items
            if item.collection_error
        )
        return EvidenceCollectionResult(
            tenant_id=authorization_context.tenant_id,
            case_id=case_id,
            correlation_id=ordered_requests[0].correlation_id,
            items=tuple(items),
            normalized_facts=facts,
            provenance=provenance,
            authoritative_store=self.authoritative_store,
            raw_store=self.raw_store,
            uncertainty=uncertainty,
        )

    def _collect_one(
        self,
        request: EvidenceRequest,
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> CollectedEvidence:
        connector = self._connectors.get(request.connector_id)
        if connector is None:
            return self._unavailable_item(
                request,
                authorization_context=authorization_context,
                reason="connector is unavailable or not configured",
                failure_state=ConnectorFailureState.UNAVAILABLE,
            )
        if connector.manifest.tenant_id != authorization_context.tenant_id:
            raise TenantAuthorizationError("configured evidence connector crosses tenant boundary")

        try:
            result = connector.read(request, authorization_context=authorization_context)
        except EvidenceConnectorError as exc:
            return self._unavailable_item(
                request,
                authorization_context=authorization_context,
                reason=str(exc),
                failure_state=exc.failure_state,
            )
        except TenantAuthorizationError:
            raise
        except Exception as exc:
            return self._unavailable_item(
                request,
                authorization_context=authorization_context,
                reason="connector response could not be collected safely",
                failure_state=ConnectorFailureState.UNAVAILABLE,
                cause=exc,
            )

        response = result.response
        if (
            response.tenant_id != authorization_context.tenant_id
            or response.case_id != request.case_id
            or response.connector_id != request.connector_id
            or response.resource_type != request.resource_type
            or response.correlation_id != request.correlation_id
        ):
            raise TenantAuthorizationError("connector response crosses evidence boundary")
        raw_checksum = checksum_for_bytes(result.raw_payload)
        evidence_id = _evidence_id(
            tenant_id=request.tenant_id,
            case_id=request.case_id,
            connector_id=request.connector_id,
            resource_type=request.resource_type,
            source_identity=response.source_identity,
            checksum=raw_checksum,
        )
        try:
            facts = normalize_response(response, evidence_id=evidence_id)
        except EvidenceNormalizationError as exc:
            facts = ()
            normalization_status = "invalid"
            normalization_error = str(exc)
        else:
            normalization_status = "normalized"
            normalization_error = None

        raw_object_uri: str | None = None
        integrity_status = "not_persisted"
        collection_error = normalization_error
        expected_checksum = response.raw_checksum or raw_checksum
        if expected_checksum.strip().lower().removeprefix("sha256:") != raw_checksum.removeprefix(
            "sha256:"
        ):
            integrity_status = "failed"
            facts = ()
            collection_error = "connector checksum does not match raw evidence bytes"
        elif self.storage is None:
            collection_error = collection_error or "raw evidence object storage is unavailable"
            facts = ()
        else:
            try:
                artifact = self.storage.persist_raw(
                    authorization_context=authorization_context,
                    case_id=request.case_id,
                    evidence_id=evidence_id,
                    resource_type=request.resource_type,
                    raw_payload=result.raw_payload,
                    expected_checksum=expected_checksum,
                )
            except (ObjectIntegrityError, OSError, ValueError) as exc:
                integrity_status = "failed"
                facts = ()
                collection_error = f"raw evidence integrity failure: {exc}"
            else:
                raw_object_uri = artifact.object_uri
                integrity_status = "verified"

        source_identifier = _source_identifier(response, facts, raw_checksum)
        provenance_values = dict(result.provenance)
        provenance = EvidenceProvenance(
            tenant_id=request.tenant_id,
            case_id=request.case_id,
            correlation_id=request.correlation_id,
            connector_id=request.connector_id,
            resource_type=request.resource_type,
            source_identity=response.source_identity,
            mode=provenance_values.get("mode", connector.manifest.mode.value),
            source=provenance_values.get("source", response.source_identity),
            version=provenance_values.get("version", connector.manifest.contract_version),
            seed=provenance_values.get("seed", "live"),
            evidence_id=evidence_id,
            raw_checksum=raw_checksum,
            original_timestamps={
                "observed_at": response.observed_at.isoformat(),
                "collected_at": response.collected_at.isoformat(),
            },
        )
        if response.failure_state is not None:
            collection_error = collection_error or response.failure_state.value
        return CollectedEvidence(
            tenant_id=response.tenant_id,
            case_id=response.case_id,
            correlation_id=response.correlation_id,
            evidence_id=evidence_id,
            connector_id=response.connector_id,
            resource_type=response.resource_type,
            source_identifier=source_identifier,
            source_identity=response.source_identity,
            observed_at=response.observed_at,
            received_at=response.collected_at,
            raw_object_uri=raw_object_uri,
            raw_checksum=raw_checksum,
            expected_checksum=expected_checksum,
            completeness=response.completeness,
            normalization_status=normalization_status,
            integrity_status=integrity_status,
            collection_error=collection_error,
            normalized_facts=facts if integrity_status == "verified" else (),
            provenance=provenance,
            response=response,
        )

    def _unavailable_item(
        self,
        request: EvidenceRequest,
        *,
        authorization_context: TenantAuthorizationContext,
        reason: str,
        failure_state: ConnectorFailureState,
        cause: BaseException | None = None,
    ) -> CollectedEvidence:
        del cause
        raw_payload = json.dumps(
            {
                "schema_version": "1.0.0",
                "tenant_id": request.tenant_id,
                "case_id": request.case_id,
                "correlation_id": request.correlation_id,
                "connector_id": request.connector_id,
                "resource_type": request.resource_type,
                "status": failure_state.value,
                "reason": reason,
                "mode": "replay" if request.connector_id.startswith("sim-") else "live",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        checksum = checksum_for_bytes(raw_payload)
        evidence_id = _evidence_id(
            tenant_id=request.tenant_id,
            case_id=request.case_id,
            connector_id=request.connector_id,
            resource_type=request.resource_type,
            source_identity=f"unavailable:{request.connector_id}",
            checksum=checksum,
        )
        raw_uri: str | None = None
        integrity_status = "not_persisted"
        if self.storage is not None:
            try:
                artifact = self.storage.persist_raw(
                    authorization_context=authorization_context,
                    case_id=request.case_id,
                    evidence_id=evidence_id,
                    resource_type=request.resource_type,
                    raw_payload=raw_payload,
                    expected_checksum=checksum,
                )
            except (ObjectIntegrityError, OSError, ValueError):
                reason = f"{reason}; raw evidence integrity failure"
            else:
                raw_uri = artifact.object_uri
                integrity_status = "verified"
        provenance = EvidenceProvenance(
            tenant_id=request.tenant_id,
            case_id=request.case_id,
            correlation_id=request.correlation_id,
            connector_id=request.connector_id,
            resource_type=request.resource_type,
            source_identity=f"unavailable:{request.connector_id}",
            mode="replay" if request.connector_id.startswith("sim-") else "live",
            source="evidence-orchestrator",
            version="1.0.0",
            seed="unavailable",
            evidence_id=evidence_id,
            raw_checksum=checksum,
            original_timestamps={
                "observed_at": request.requested_at.isoformat(),
                "collected_at": request.requested_at.isoformat(),
            },
        )
        return CollectedEvidence(
            tenant_id=authorization_context.tenant_id,
            case_id=request.case_id,
            correlation_id=request.correlation_id,
            evidence_id=evidence_id,
            connector_id=request.connector_id,
            resource_type=request.resource_type,
            source_identifier=f"unavailable:{request.connector_id}",
            source_identity=f"unavailable:{request.connector_id}",
            observed_at=request.requested_at,
            received_at=request.requested_at,
            raw_object_uri=raw_uri,
            raw_checksum=checksum,
            expected_checksum=checksum,
            completeness="partial",
            normalization_status="not_attempted",
            integrity_status=integrity_status,
            collection_error=reason,
            normalized_facts=(),
            provenance=provenance,
        )

    def _persist_metadata(
        self,
        items: Iterable[CollectedEvidence],
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        assert self.unit_of_work_factory is not None
        items = tuple(items)
        if not items:
            return
        try:
            with self.unit_of_work_factory(authorization_context) as unit_of_work:
                for item in items:
                    create_or_get = getattr(unit_of_work.evidence, "create_or_get", None)
                    if create_or_get is not None:
                        create_or_get(
                            evidence_id=item.evidence_id,
                            case_id=item.case_id,
                            connector_id=item.connector_id,
                            resource_type=item.resource_type,
                            source_identifier=item.source_identifier,
                            observed_at=item.observed_at,
                            received_at=item.received_at,
                            raw_object_uri=item.raw_object_uri,
                            checksum=item.raw_checksum,
                            normalization_status=item.normalization_status,
                            completeness=item.completeness,
                            trust_classification=item.trust_classification,
                            collection_error=item.collection_error,
                        )
                    else:
                        unit_of_work.evidence.create(
                            evidence_id=item.evidence_id,
                            case_id=item.case_id,
                            connector_id=item.connector_id,
                            resource_type=item.resource_type,
                            source_identifier=item.source_identifier,
                            observed_at=item.observed_at,
                            received_at=item.received_at,
                            raw_object_uri=item.raw_object_uri,
                            checksum=item.raw_checksum,
                            normalization_status=item.normalization_status,
                            completeness=item.completeness,
                            trust_classification=item.trust_classification,
                            collection_error=item.collection_error,
                        )
                transition = getattr(unit_of_work.cases, "transition_state", None)
                if transition is not None:
                    transition(case_id=items[0].case_id, new_state="collecting_evidence")
        except Exception as exc:
            raise EvidenceCollectionError(
                "authoritative evidence metadata could not be persisted"
            ) from exc

    @staticmethod
    def _require_authorization(
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        if not isinstance(authorization_context, TenantAuthorizationContext):
            raise TenantAuthorizationError(
                "evidence collection requires authenticated authorization"
            )


def _request_sort_key(request: EvidenceRequest) -> tuple[object, ...]:
    return (
        request.resource_type,
        request.connector_id,
        request.operation,
        tuple(request.resource_ids),
        request.page_size,
        request.cursor or "",
        request.requested_at,
    )


def _evidence_id(
    *,
    tenant_id: str,
    case_id: str,
    connector_id: str,
    resource_type: str,
    source_identity: str,
    checksum: str,
) -> str:
    canonical = "|".join(
        (tenant_id, case_id, connector_id, resource_type, source_identity, checksum)
    ).encode("utf-8")
    return f"evidence-{hashlib.sha256(canonical).hexdigest()[:32]}"


def _source_identifier(
    response: EvidenceResponse,
    facts: tuple[Any, ...],
    checksum: str,
) -> str:
    if facts:
        return "|".join(sorted({fact.source_event_id for fact in facts}))
    return f"{response.resource_type}:response:{checksum}"


__all__ = ["EvidenceCollectionError", "EvidenceOrchestrator"]
