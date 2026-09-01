"""Versioned, trusted metadata for the deterministic LightGBM baseline.

The initial repository contains a replay fixture rather than a remotely fetched
serialized model.  The manifest is therefore the explicit loading boundary: it
validates lineage and the fixed feature contract before the adapter can predict.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

LIGHTGBM_SCHEMA_VERSION = "1.0.0"
LIGHTGBM_MODEL_VERSION = "lightgbm-baseline-v1.0.0"
LIGHTGBM_FEATURE_SCHEMA_VERSION = "lightgbm-features-v1.0.0"
LIGHTGBM_MODEL_FAMILY = "lightgbm"
LIGHTGBM_METHOD = "lightgbm"
LIGHTGBM_FEATURE_ORDER = (
    "payment_amount_minor",
    "new_device",
    "profile_change_24h",
    "session_velocity_5m",
    "successful_customer_orders",
)


@dataclass(frozen=True, slots=True)
class LightGBMManifest:
    """Trusted model/feature metadata validated before adapter construction."""

    schema_version: str
    fixture_version: str
    feature_schema_version: str
    model_family: str
    model_version: str
    feature_order: tuple[str, ...]
    artifact_reference: str
    mode: str = "replay"
    production_performance_claim: bool = False
    metrics: object | None = None
    tenant_id: str | None = None
    case_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "schema_version",
            "fixture_version",
            "feature_schema_version",
            "model_family",
            "model_version",
            "artifact_reference",
            "mode",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"LightGBM manifest {name} is required")
        if self.schema_version != LIGHTGBM_SCHEMA_VERSION:
            raise ValueError("unsupported LightGBM manifest schema version")
        if self.model_family != LIGHTGBM_MODEL_FAMILY:
            raise ValueError("LightGBM manifest model family is invalid")
        if self.model_version != self.fixture_version:
            raise ValueError("LightGBM model version must match fixture version")
        if self.feature_schema_version != LIGHTGBM_FEATURE_SCHEMA_VERSION:
            raise ValueError("unsupported LightGBM feature schema version")
        if self.mode != "replay":
            raise ValueError("the baseline adapter accepts replay fixtures only")
        if self.production_performance_claim or self.metrics is not None:
            raise ValueError("the baseline fixture cannot make a production performance claim")
        if tuple(self.feature_order) != LIGHTGBM_FEATURE_ORDER:
            raise ValueError("LightGBM feature order is incompatible with the baseline")
        if self.tenant_id is not None and not self.tenant_id.strip():
            raise ValueError("LightGBM manifest tenant_id cannot be empty")
        if self.case_id is not None and not self.case_id.strip():
            raise ValueError("LightGBM manifest case_id cannot be empty")
        object.__setattr__(self, "feature_order", tuple(self.feature_order))

    @classmethod
    def from_fixture(cls, fixture: Mapping[str, Any]) -> LightGBMManifest:
        if not isinstance(fixture, Mapping):
            raise ValueError("LightGBM fixture must be an object")
        provenance = fixture.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("LightGBM fixture provenance is required")
        claim_boundary = fixture.get("claim_boundary")
        if claim_boundary != {"production_performance_claim": False, "metrics": None}:
            raise ValueError("LightGBM fixture claim boundary is invalid")
        feature_order = fixture.get("feature_schema")
        if not isinstance(feature_order, Sequence) or isinstance(feature_order, str | bytes):
            raise ValueError("LightGBM feature schema is required")
        required = {
            "schema_version": fixture.get("schema_version"),
            "fixture_version": fixture.get("fixture_version"),
            "feature_schema_version": provenance.get("feature_schema_version"),
            "model_family": provenance.get("model_family"),
            "model_version": provenance.get("model_version"),
            "artifact_reference": provenance.get("artifact_reference"),
            "mode": fixture.get("mode"),
        }
        tenant_id = _optional_text(fixture.get("tenant_id"), "tenant_id")
        case_id = _optional_text(fixture.get("case_id"), "case_id")
        if tenant_id is None or case_id is None:
            raise ValueError("LightGBM fixture tenant_id and case_id are required")
        manifest = cls(
            **required,
            feature_order=tuple(feature_order),
            tenant_id=tenant_id,
            case_id=case_id,
        )
        events = fixture.get("events")
        if not isinstance(events, Sequence) or isinstance(events, str | bytes):
            raise ValueError("LightGBM fixture events are required")
        if not events:
            raise ValueError("LightGBM fixture must contain events")
        return manifest


LightGBMFeatureManifest = LightGBMManifest


def baseline_manifest() -> LightGBMManifest:
    """Return the built-in manifest for non-fixture replay inputs."""

    return LightGBMManifest(
        schema_version=LIGHTGBM_SCHEMA_VERSION,
        fixture_version=LIGHTGBM_MODEL_VERSION,
        feature_schema_version=LIGHTGBM_FEATURE_SCHEMA_VERSION,
        model_family=LIGHTGBM_MODEL_FAMILY,
        model_version=LIGHTGBM_MODEL_VERSION,
        feature_order=LIGHTGBM_FEATURE_ORDER,
        artifact_reference="fixture://attribution/lightgbm/baseline-v1.0.0",
    )


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"LightGBM fixture {name} is invalid")
    return value.strip()


__all__ = [
    "LIGHTGBM_FEATURE_ORDER",
    "LIGHTGBM_FEATURE_SCHEMA_VERSION",
    "LIGHTGBM_METHOD",
    "LIGHTGBM_MODEL_FAMILY",
    "LIGHTGBM_MODEL_VERSION",
    "LIGHTGBM_SCHEMA_VERSION",
    "LightGBMManifest",
    "LightGBMFeatureManifest",
    "baseline_manifest",
]
