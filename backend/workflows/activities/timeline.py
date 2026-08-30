"""Temporal activity for rebuilding a timeline from persisted US1 evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.auth.oidc import IdentityType, TenantAuthorizationContext, TenantAuthorizationError
from app.db.unit_of_work import PostgresUnitOfWork
from app.storage.minio_evidence import ObjectIntegrityError
from evidence.models import CollectedEvidence, EvidenceProvenance
from evidence.normalization import EvidenceNormalizationError, normalize_response
from evidence.storage import EvidenceStorage
from packages.contracts.connectors import EvidenceResponse
from temporalio import activity
from temporalio.exceptions import ApplicationError
from timeline.reconstruct import TimelineReconstructor

from workflows.commands import CaseWorkflowCommand

UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]
AuthorizationContextFactory = Callable[[str], TenantAuthorizationContext]


@dataclass(frozen=True, slots=True)
class TimelineActivityDependencies:
    """Trusted worker wiring for the persisted-evidence timeline boundary."""

    reconstructor: TimelineReconstructor
    evidence_storage: EvidenceStorage
    unit_of_work_factory: UnitOfWorkFactory
    authorization_context_factory: AuthorizationContextFactory


class TimelineActivities:
    """Reconstruct and persist the canonical timeline in a Temporal activity."""

    def __init__(self, dependencies: TimelineActivityDependencies) -> None:
        self.dependencies = dependencies

    @activity.defn(name="case.rebuild_timeline")
    async def rebuild_timeline(self, command: CaseWorkflowCommand) -> dict[str, Any]:
        context = self.dependencies.authorization_context_factory(command.tenant_id)
        if (
            not isinstance(context, TenantAuthorizationContext)
            or context.tenant_id != command.tenant_id
            or context.identity_type is not IdentityType.SERVICE
        ):
            raise ApplicationError(
                "timeline activity service context is not tenant-bound",
                non_retryable=True,
            )
        try:
            evidence = self._load_evidence(command, context)
            facts = tuple(fact for item in evidence for fact in item.normalized_facts)
            result = self.dependencies.reconstructor.rebuild(
                case_id=command.case_id,
                evidence=evidence,
                normalized_facts=facts,
                authorization_context=context,
            )
        except (
            ObjectIntegrityError,
            EvidenceNormalizationError,
            TenantAuthorizationError,
            ValueError,
        ) as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc
        except Exception as exc:
            raise ApplicationError("timeline reconstruction activity failed") from exc
        return {
            "tenant_id": result.tenant_id,
            "case_id": result.case_id,
            "state": result.state,
            "authoritative": result.authoritative_store == "postgresql",
            "timeline_event_count": len(result.events),
            "normalized_fact_count": len(result.normalized_facts),
            "uncertainty": result.uncertainty,
        }

    def _load_evidence(
        self,
        command: CaseWorkflowCommand,
        context: TenantAuthorizationContext,
    ) -> tuple[CollectedEvidence, ...]:
        with self.dependencies.unit_of_work_factory(context) as unit_of_work:
            rows = tuple(unit_of_work.evidence.for_case(case_id=command.case_id))
        return tuple(
            self._row_to_evidence(row, command=command, context=context) for row in rows
        )

    def _row_to_evidence(
        self,
        row: Any,
        *,
        command: CaseWorkflowCommand,
        context: TenantAuthorizationContext,
    ) -> CollectedEvidence:
        tenant_id = str(row[0])
        evidence_id = str(row[1])
        case_id = str(row[2])
        if tenant_id != context.tenant_id or case_id != command.case_id:
            raise ValueError("persisted evidence does not match the workflow identity")

        raw_object_uri = None if row[8] is None else str(row[8])
        expected_checksum = None if row[9] is None else str(row[9])
        normalized = str(row[10]) == "normalized"
        if not normalized or raw_object_uri is None or expected_checksum is None:
            return CollectedEvidence(
                tenant_id=tenant_id,
                case_id=case_id,
                correlation_id=command.correlation_id,
                evidence_id=evidence_id,
                connector_id=str(row[3]),
                resource_type=str(row[4]),
                source_identifier=str(row[5]),
                source_identity=str(row[5]),
                observed_at=row[6] or row[7],
                received_at=row[7],
                raw_object_uri=raw_object_uri,
                raw_checksum=expected_checksum or "not-available",
                expected_checksum=expected_checksum or "not-available",
                completeness=str(row[11]),
                normalization_status=str(row[10]),
                integrity_status="not_verified",
                trust_classification=str(row[12]),
                collection_error=None if row[13] is None else str(row[13]),
            )

        raw_payload, raw_checksum = self.dependencies.evidence_storage.read_raw(
            authorization_context=context,
            object_uri=raw_object_uri,
            expected_checksum=expected_checksum,
        )
        try:
            raw_document = json.loads(raw_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("persisted evidence object is not valid JSON") from exc
        if not isinstance(raw_document, Mapping):
            raise ValueError("persisted evidence object must be a JSON object")
        raw_facts = raw_document.get("normalized_facts", [])
        if not isinstance(raw_facts, list):
            raise ValueError("persisted evidence normalized_facts must be a list")

        observed_at = row[6] or _parse_timestamp(raw_document.get("observed_at"))
        received_at = row[7] or _parse_timestamp(raw_document.get("collected_at"))
        if observed_at is None or received_at is None:
            raise ValueError("persisted evidence timestamps are incomplete")
        source_identity = str(
            raw_document.get("source_identity") or f"persisted:{row[3]}"
        )
        response = EvidenceResponse(
            tenant_id=tenant_id,
            correlation_id=command.correlation_id,
            case_id=case_id,
            connector_id=str(row[3]),
            source_identity=source_identity,
            resource_type=str(row[4]),
            observed_at=observed_at,
            collected_at=received_at,
            completeness=str(row[11]),
            raw_artifact_reference=raw_object_uri,
            raw_checksum=raw_checksum,
            normalized_facts=raw_facts,
            connector_status=str(raw_document.get("connector_status") or "persisted"),
        )
        facts = normalize_response(response, evidence_id=evidence_id)
        provenance_values = raw_document.get("provenance", {})
        if not isinstance(provenance_values, Mapping):
            provenance_values = {}
        provenance = EvidenceProvenance(
            tenant_id=tenant_id,
            case_id=case_id,
            correlation_id=command.correlation_id,
            connector_id=str(row[3]),
            resource_type=str(row[4]),
            source_identity=source_identity,
            mode=str(raw_document.get("mode") or "live"),
            source=str(provenance_values.get("source") or source_identity),
            version=str(provenance_values.get("version") or "persisted"),
            seed=str(raw_document.get("seed") or "persisted"),
            evidence_id=evidence_id,
            raw_checksum=raw_checksum,
            original_timestamps={
                "observed_at": observed_at.isoformat(),
                "collected_at": received_at.isoformat(),
            },
        )
        return CollectedEvidence(
            tenant_id=tenant_id,
            case_id=case_id,
            correlation_id=command.correlation_id,
            evidence_id=evidence_id,
            connector_id=str(row[3]),
            resource_type=str(row[4]),
            source_identifier=str(row[5]),
            source_identity=source_identity,
            observed_at=observed_at,
            received_at=received_at,
            raw_object_uri=raw_object_uri,
            raw_checksum=raw_checksum,
            expected_checksum=expected_checksum,
            completeness=str(row[11]),
            normalization_status=str(row[10]),
            integrity_status="verified",
            trust_classification=str(row[12]),
            collection_error=None if row[13] is None else str(row[13]),
            normalized_facts=facts,
            provenance=provenance,
            response=response,
        )


def make_timeline_activities(
    dependencies: TimelineActivityDependencies,
) -> TimelineActivities:
    """Build the production timeline activity object for worker registration."""

    return TimelineActivities(dependencies)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("persisted evidence timestamp is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("persisted evidence timestamp lacks explicit timezone")
    return parsed.astimezone(UTC)


__all__ = [
    "TimelineActivities",
    "TimelineActivityDependencies",
    "make_timeline_activities",
]
