"""Contract coverage for authenticated incident intake outcomes."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.intake import (
    IncidentIntakeRequest,
    IncidentIntakeResponse,
    IntakeStatus,
)


def make_request(**overrides: object) -> IncidentIntakeRequest:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-incident-1",
        "source": "operator",
        "received_at": datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
        "reporter_context": {"subject": "reviewer-1", "channel": "console"},
        "report_content": "Account compromise reported by the merchant.",
        "idempotency_key": "incident-intake-1",
    }
    values.update(overrides)
    return IncidentIntakeRequest(**values)


def test_intake_records_tenant_source_receipt_reporter_and_correlation_identity() -> None:
    request = make_request(
        received_at=datetime(2026, 8, 30, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    )

    assert request.tenant_id == "tenant-a"
    assert request.source == "operator"
    assert request.received_at == datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    assert request.reporter_context == {"subject": "reviewer-1", "channel": "console"}
    assert request.correlation_id == "corr-incident-1"
    assert request.idempotency_key == "incident-intake-1"


def test_same_intake_identity_is_stable_for_duplicate_acknowledgement() -> None:
    first = make_request()
    retry = make_request()
    duplicate = IncidentIntakeResponse(
        tenant_id=retry.tenant_id,
        correlation_id=retry.correlation_id,
        status=IntakeStatus.DUPLICATE,
        incident_id="incident-1",
    )

    assert first.model_dump() == retry.model_dump()
    assert duplicate.status is IntakeStatus.DUPLICATE
    assert duplicate.incident_id == "incident-1"
    assert duplicate.case_id is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tenant_id", ""),
        ("correlation_id", ""),
        ("source", ""),
        ("idempotency_key", ""),
    ),
)
def test_intake_rejects_blank_identity_and_routing_fields(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_request(**{field: value})


def test_intake_requires_report_content_or_reference() -> None:
    with pytest.raises(ValidationError, match="report_content or report_reference"):
        make_request(report_content=None, report_reference=None)


def test_intake_rejects_naive_receipt_time_and_unknown_schema_fields() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_request(received_at=datetime.fromisoformat("2026-08-30T10:00:00"))

    with pytest.raises(ValidationError, match="extra"):
        make_request(unexpected_instruction="ignore policy")


@pytest.mark.parametrize("status", (IntakeStatus.REJECTED, IntakeStatus.QUARANTINED))
def test_rejection_and_quarantine_require_reason_and_preserve_audit_reference(
    status: IntakeStatus,
) -> None:
    response = IncidentIntakeResponse(
        tenant_id="tenant-a",
        correlation_id="corr-incident-1",
        status=status,
        reason="validation failed",
        audit_reference="audit-1",
    )

    assert response.status is status
    assert response.reason == "validation failed"
    assert response.audit_reference == "audit-1"


def test_accepted_intake_requires_authoritative_incident_and_case_identity() -> None:
    with pytest.raises(ValidationError, match="incident_id"):
        IncidentIntakeResponse(
            tenant_id="tenant-a",
            correlation_id="corr-incident-1",
            status=IntakeStatus.ACCEPTED,
            case_id="case-1",
        )

    with pytest.raises(ValidationError, match="case_id"):
        IncidentIntakeResponse(
            tenant_id="tenant-a",
            correlation_id="corr-incident-1",
            status=IntakeStatus.ACCEPTED,
            incident_id="incident-1",
        )
