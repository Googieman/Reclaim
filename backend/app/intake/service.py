"""Tenant-bound incident intake and authoritative case creation."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from packages.contracts.audit_replay import AuditRecord
from packages.contracts.intake import IncidentIntakeRequest, IncidentIntakeResponse, IntakeStatus

from app.audit.chain import AuditChain
from app.auth.oidc import RequiredRole, TenantAuthorizationContext, TenantAuthorizationError
from app.cases.service import CaseService
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.incident_events import build_incident_accepted_event
from app.incidents.service import IncidentService


class IntakeServiceError(RuntimeError):
    """Raised when an authenticated intake command cannot be persisted safely."""


UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]
IdFactory = Callable[[str], str]


class IncidentIntakeService:
    """Persist one authenticated incident and its case in one PostgreSQL transaction.

    The request tenant is checked against the already verified single-tenant
    authorization context.  Report content is retained only as untrusted input to
    the incident repository; event payloads contain metadata and references, not
    arbitrary report instructions.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        id_factory: IdFactory | None = None,
        producer: str = "intake-api@1.0.0",
    ) -> None:
        if not producer.strip():
            raise ValueError("producer is required")
        self.unit_of_work_factory = unit_of_work_factory
        self.id_factory = id_factory or (lambda prefix: f"{prefix}-{uuid4().hex}")
        self.producer = producer
        self.incidents = IncidentService(id_factory=self.id_factory)
        self.cases = CaseService(id_factory=self.id_factory)

    def accept(
        self,
        request: IncidentIntakeRequest,
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> IncidentIntakeResponse:
        """Accept or duplicate-acknowledge an authenticated incident report."""

        _require_intake_authorization(request, authorization_context)
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            result = self.incidents.create_or_get(
                unit_of_work,
                source=request.source,
                reporter_context=request.reporter_context,
                received_at=request.received_at,
                correlation_key=request.correlation_id,
                raw_input_reference=request.report_reference,
                intake_status=IntakeStatus.ACCEPTED.value,
                deduplication_identity=request.idempotency_key,
            )
            incident_id = str(result.row[1])

            if result.inserted:
                case_row = self.cases.create(
                    unit_of_work, incident_id=incident_id, created_at=request.received_at
                )
                case_id = str(case_row[1])
                event = build_incident_accepted_event(
                    tenant_id=request.tenant_id,
                    correlation_id=request.correlation_id,
                    incident_id=incident_id,
                    case_id=case_id,
                    source=request.source,
                    received_at=request.received_at,
                    report_reference=request.report_reference,
                    report_content_present=bool(request.report_content),
                    causation_id=f"intake:{request.idempotency_key}",
                    producer=self.producer,
                )
                unit_of_work.outbox.enqueue(
                    outbox_id=self.id_factory("outbox"),
                    event=event,
                )
                outcome = IntakeStatus.ACCEPTED.value
            else:
                case_row = self.cases.find_by_incident(unit_of_work, incident_id=incident_id)
                if case_row is None:
                    raise IntakeServiceError("duplicate incident has no authoritative case")
                case_id = str(case_row[1])
                outcome = IntakeStatus.DUPLICATE.value

            audit_record = _append_intake_audit(
                unit_of_work=unit_of_work,
                request=request,
                incident_id=incident_id,
                case_id=case_id,
                actor=authorization_context.subject,
                outcome=outcome,
                id_factory=self.id_factory,
            )

        return IncidentIntakeResponse(
            tenant_id=authorization_context.tenant_id,
            correlation_id=str(result.row[4]),
            status=IntakeStatus(outcome),
            incident_id=incident_id,
            case_id=case_id,
            audit_reference=audit_record.audit_id,
        )


def _require_intake_authorization(
    request: IncidentIntakeRequest,
    authorization_context: TenantAuthorizationContext,
) -> None:
    if request.tenant_id != authorization_context.tenant_id:
        raise TenantAuthorizationError(
            "intake request tenant does not match authenticated tenant context"
        )
    authorization_context.require_role(RequiredRole.REVIEWER)


def _append_intake_audit(
    *,
    unit_of_work: PostgresUnitOfWork,
    request: IncidentIntakeRequest,
    incident_id: str,
    case_id: str,
    actor: str,
    outcome: str,
    id_factory: IdFactory,
) -> AuditRecord:
    chain = AuditChain(unit_of_work.audit)
    record = chain.build_record(
        tenant_id=request.tenant_id,
        audit_id=id_factory("audit"),
        case_id=case_id,
        actor=actor,
        action="incident.intake",
        input_references=(request.idempotency_key,),
        output_references=(incident_id, case_id),
        correlation_ids=(request.correlation_id,),
        outcome=outcome,
        recorded_at=request.received_at,
    )
    return chain.append(record)
