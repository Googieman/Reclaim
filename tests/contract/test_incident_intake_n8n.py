"""Contract regressions for typed incident intake and the n8n handoff."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.events.incident_events import build_incident_accepted_event
from packages.contracts.intake import IncidentIntakeRequest, IncidentType
from packages.contracts.money import MoneyParseError, decimal_to_minor_units
from packages.contracts.orchestration import OrchestrationStageRequest
from pydantic import ValidationError


def test_structured_intake_requires_the_minimum_incident_fields() -> None:
    request = IncidentIntakeRequest(
        tenant_id="tenant-1",
        correlation_id="correlation-1",
        source="merchant-console",
        received_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
        incident_type=IncidentType.ACCOUNT_TAKEOVER,
        occurred_at=datetime(2026, 9, 3, 8, 30, tzinfo=UTC),
        narrative="Customer reports an unexpected sign-in.",
        reported_amount_minor=12500,
        reported_currency="inr",
        idempotency_key="incident:001",
    )

    assert request.reported_currency == "INR"
    assert request.incident_type is IncidentType.ACCOUNT_TAKEOVER

    with pytest.raises(ValidationError, match="incident_type"):
        IncidentIntakeRequest(
            tenant_id="tenant-1",
            correlation_id="correlation-2",
            source="merchant-console",
            received_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
            idempotency_key="incident:002",
        )


def test_reported_money_is_deterministically_normalized_to_minor_units() -> None:
    assert decimal_to_minor_units("125.50", "INR") == 12550
    assert decimal_to_minor_units("125", "JPY") == 125
    with pytest.raises(MoneyParseError):
        decimal_to_minor_units("125.001", "INR")
    with pytest.raises(MoneyParseError):
        decimal_to_minor_units("1.00", "XXX")


def test_incident_accepted_event_contains_metadata_but_not_narrative() -> None:
    event = build_incident_accepted_event(
        tenant_id="tenant-1",
        correlation_id="correlation-1",
        incident_id="incident-1",
        case_id="case-1",
        source="merchant-console",
        received_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
        report_reference="raw-report-1",
        report_content_present=True,
        causation_id="request-1",
        producer="reclaim-api",
        incident_type="account_takeover",
        narrative_checksum="sha256:narrative",
        customer_reference="customer-1",
    )

    assert event.payload["incident_type"] == "account_takeover"
    assert event.payload["narrative_checksum"] == "sha256:narrative"
    assert "narrative" not in event.payload
    assert "report_content" not in event.payload


def test_orchestration_stage_contract_requires_expected_state_and_is_strict() -> None:
    request = OrchestrationStageRequest(
        expected_state="intake_received",
        idempotency_key="normalize:incident-1",
    )
    assert request.expected_state == "intake_received"

    with pytest.raises(ValidationError):
        OrchestrationStageRequest(idempotency_key="normalize:incident-1")
    with pytest.raises(ValidationError):
        OrchestrationStageRequest(
            expected_state="intake_received",
            idempotency_key="normalize:incident-1",
            shell="Get-ChildItem",
        )
