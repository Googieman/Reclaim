"""Authoritative PostgreSQL repository for deterministic exposure results."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from finance.exposure import FinancialExposure

from .base import TenantScopedRepository


class FinancialExposureRepository(TenantScopedRepository):
    """Persist only already-validated trusted exposure values in PostgreSQL."""

    def create(
        self,
        *,
        exposure_id: str,
        case_id: str,
        currency: str,
        gross_exposure_minor: int,
        recoverable_value_minor: int,
        contained_value_minor: int,
        legitimate_value_disrupted_minor: int,
        irreversible_loss_minor: int,
        remaining_exposure_minor: int,
        calculation_version: str,
        source_references: Sequence[str],
        calculated_at: datetime | None = None,
    ) -> object:
        """Insert a case result after enforcing its arithmetic invariants."""

        _required_text(exposure_id, "exposure_id")
        _required_text(case_id, "case_id")
        exposure = FinancialExposure(
            tenant_id=self.tenant_context.tenant_id,
            case_id=case_id,
            currency=currency,
            gross_exposure_minor=gross_exposure_minor,
            recoverable_value_minor=recoverable_value_minor,
            contained_value_minor=contained_value_minor,
            legitimate_value_disrupted_minor=legitimate_value_disrupted_minor,
            irreversible_loss_minor=irreversible_loss_minor,
            remaining_exposure_minor=remaining_exposure_minor,
            calculation_version=calculation_version,
            source_references=tuple(source_references),
        )
        row = self.fetch_one(
            """
            INSERT INTO financial_exposures (
                tenant_id, exposure_id, case_id, currency, gross_exposure_minor,
                recoverable_value_minor, contained_value_minor,
                legitimate_value_disrupted_minor, irreversible_loss_minor,
                remaining_exposure_minor, calculation_version, source_references,
                calculated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                    COALESCE(%s, now()))
            RETURNING tenant_id, exposure_id, case_id, currency, gross_exposure_minor,
                      recoverable_value_minor, contained_value_minor,
                      legitimate_value_disrupted_minor, irreversible_loss_minor,
                      remaining_exposure_minor, calculation_version, source_references,
                      calculated_at
            """,
            (
                self.tenant_context.tenant_id,
                exposure_id,
                exposure.case_id,
                exposure.currency,
                exposure.gross_exposure_minor,
                exposure.recoverable_value_minor,
                exposure.contained_value_minor,
                exposure.legitimate_value_disrupted_minor,
                exposure.irreversible_loss_minor,
                exposure.remaining_exposure_minor,
                exposure.calculation_version,
                json.dumps(list(exposure.source_references), separators=(",", ":")),
                calculated_at,
            ),
        )
        if row is None:
            raise RuntimeError("financial exposure insert returned no row")
        return row

    def create_result(self, *, exposure_id: str, exposure: FinancialExposure) -> object:
        """Persist a calculator result without accepting caller tenant authority."""

        self.assert_tenant(exposure.tenant_id)
        return self.create(
            exposure_id=exposure_id,
            case_id=exposure.case_id,
            currency=exposure.currency,
            gross_exposure_minor=exposure.gross_exposure_minor,
            recoverable_value_minor=exposure.recoverable_value_minor,
            contained_value_minor=exposure.contained_value_minor,
            legitimate_value_disrupted_minor=exposure.legitimate_value_disrupted_minor,
            irreversible_loss_minor=exposure.irreversible_loss_minor,
            remaining_exposure_minor=exposure.remaining_exposure_minor,
            calculation_version=exposure.calculation_version,
            source_references=exposure.source_references,
        )

    def for_case(self, *, case_id: str) -> list[object]:
        _required_text(case_id, "case_id")
        return self.fetch_all(
            """
            SELECT tenant_id, exposure_id, case_id, currency, gross_exposure_minor,
                   recoverable_value_minor, contained_value_minor,
                   legitimate_value_disrupted_minor, irreversible_loss_minor,
                   remaining_exposure_minor, calculation_version, source_references,
                   calculated_at
            FROM financial_exposures
            WHERE tenant_id = %s AND case_id = %s
            ORDER BY calculated_at, exposure_id
            """,
            (self.tenant_context.tenant_id, case_id),
        )


ExposureRepository = FinancialExposureRepository


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"exposure repository {name} is required")
    return value.strip()


__all__ = ["ExposureRepository", "FinancialExposureRepository"]
