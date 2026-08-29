from datetime import datetime, timezone

import pytest

from packages.contracts.intake import (
    IncidentIntakeRequest,
    IncidentIntakeResponse,
    IntakeStatus,
)

CONTEXT = {"tenant_id": "tenant-a", "correlation_id": "corr-1"}


def test_intake_request_requires_tenant_correlation_and_report() -> None:
    request = IncidentIntakeRequest(
        **CONTEXT,
        source="operator",
        received_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        report_content="Account compromise reported",
        idempotency_key="incident-1",
    )
    assert request.received_at.tzinfo == timezone.utc

    with pytest.raises(ValueError, match="report_content"):
        IncidentIntakeRequest(
            **CONTEXT,
            source="operator",
            received_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
            idempotency_key="incident-2",
        )


def test_intake_outcomes_cover_acceptance_duplicate_rejection_and_quarantine() -> None:
    accepted = IncidentIntakeResponse(
        **CONTEXT, status=IntakeStatus.ACCEPTED, incident_id="i-1", case_id="c-1"
    )
    duplicate = IncidentIntakeResponse(
        **CONTEXT, status=IntakeStatus.DUPLICATE, incident_id="i-1"
    )
    assert accepted.status == "accepted"
    assert duplicate.status == "duplicate"
    with pytest.raises(ValueError, match="reason"):
        IncidentIntakeResponse(**CONTEXT, status=IntakeStatus.QUARANTINED)
