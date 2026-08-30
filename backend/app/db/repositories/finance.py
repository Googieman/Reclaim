"""Authoritative integer-minor-unit exposure repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import json

from .base import TenantScopedRepository


class FinancialExposureRepository(TenantScopedRepository):
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
                      remaining_exposure_minor
            """,
            (
                self.tenant_context.tenant_id,
                exposure_id,
                case_id,
                currency,
                gross_exposure_minor,
                recoverable_value_minor,
                contained_value_minor,
                legitimate_value_disrupted_minor,
                irreversible_loss_minor,
                remaining_exposure_minor,
                calculation_version,
                json.dumps(list(source_references), separators=(",", ":")),
                calculated_at,
            ),
        )
        if row is None:
            raise RuntimeError("financial exposure insert returned no row")
        return row
