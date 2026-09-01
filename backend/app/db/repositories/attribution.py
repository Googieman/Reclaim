"""Authoritative advisory attribution repository."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import datetime

from packages.contracts.analysis_policy import AttributionLabel, AttributionSuggestion

from .base import TenantScopedRepository


class AttributionRepository(TenantScopedRepository):
    """Persist advisory results under the authenticated tenant context."""

    def create(
        self,
        *,
        attribution_id: str,
        timeline_event_id: str,
        label: str,
        confidence: float,
        rationale: str,
        method: str,
        model_or_rules_version: str,
        evidence_references: Sequence[str],
        created_at: datetime | None = None,
    ) -> object:
        label_value = _label(label)
        if isinstance(confidence, bool) or not isinstance(confidence, int | float):
            raise ValueError("attribution confidence must be numeric")
        if not math.isfinite(float(confidence)) or not 0 <= confidence <= 1:
            raise ValueError("attribution confidence must be between 0 and 1")
        _required_text(rationale, "rationale")
        _required_text(method, "method")
        _required_text(model_or_rules_version, "model_or_rules_version")
        _references(evidence_references)
        row = self.fetch_one(
            """
            INSERT INTO attributions (
                tenant_id, attribution_id, timeline_event_id, label, confidence,
                rationale, method, model_or_rules_version, evidence_references, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, COALESCE(%s, now()))
            RETURNING tenant_id, attribution_id, timeline_event_id, label, confidence
            """,
            (
                self.tenant_context.tenant_id,
                attribution_id,
                timeline_event_id,
                label_value,
                confidence,
                rationale,
                method,
                model_or_rules_version,
                json.dumps(sorted(set(evidence_references)), separators=(",", ":")),
                created_at,
            ),
        )
        if row is None:
            raise RuntimeError("attribution insert returned no row")
        return row

    def create_suggestion(
        self,
        *,
        attribution_id: str,
        suggestion: AttributionSuggestion,
        created_at: datetime | None = None,
    ) -> object:
        """Persist a shared attribution contract without accepting tenant input."""

        if not isinstance(suggestion, AttributionSuggestion):
            raise TypeError("suggestion must be an AttributionSuggestion")
        return self.create(
            attribution_id=attribution_id,
            timeline_event_id=suggestion.timeline_event_id,
            label=suggestion.label,
            confidence=suggestion.confidence,
            rationale=suggestion.rationale,
            method=suggestion.method,
            model_or_rules_version=suggestion.model_or_rules_version,
            evidence_references=suggestion.evidence_references,
            created_at=created_at,
        )

    def for_timeline_event(self, *, timeline_event_id: str) -> list[object]:
        _required_text(timeline_event_id, "timeline_event_id")
        return self.fetch_all(
            """
            SELECT tenant_id, attribution_id, timeline_event_id, label, confidence,
                   rationale, method, model_or_rules_version, evidence_references, created_at
            FROM attributions
            WHERE tenant_id = %s AND timeline_event_id = %s
            ORDER BY created_at, attribution_id
            """,
            (self.tenant_context.tenant_id, timeline_event_id),
        )

    def for_case(self, *, case_id: str) -> list[object]:
        _required_text(case_id, "case_id")
        return self.fetch_all(
            """
            SELECT a.tenant_id, a.attribution_id, a.timeline_event_id, a.label,
                   a.confidence, a.rationale, a.method, a.model_or_rules_version,
                   a.evidence_references, a.created_at
            FROM attributions AS a
            JOIN timeline_events AS t
              ON t.tenant_id = a.tenant_id
             AND t.timeline_event_id = a.timeline_event_id
            WHERE a.tenant_id = %s AND t.case_id = %s
            ORDER BY t.effective_at, t.ordering_key, a.method, a.attribution_id
            """,
            (self.tenant_context.tenant_id, case_id),
        )


def _label(value: object) -> str:
    if isinstance(value, AttributionLabel):
        return value.value
    if not isinstance(value, str) or value.strip().lower() not in {
        label.value for label in AttributionLabel
    }:
        raise ValueError("attribution label is unsupported")
    return value.strip().lower()


def _references(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str | bytes):
        raise ValueError("attribution evidence references must be a sequence")
    values = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError("attribution evidence references contain an invalid value")
    return tuple(sorted(set(item.strip() for item in values)))


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"attribution {name} is required")
    return value.strip()
