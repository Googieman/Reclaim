"""Safe deterministic adapter for the approved LightGBM replay baseline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from packages.contracts.analysis_policy import AttributionLabel, AttributionSuggestion

from .lightgbm_manifest import (
    LIGHTGBM_METHOD,
    LightGBMManifest,
    baseline_manifest,
)


class LightGBMBaselineAdapter:
    """A side-effect-free, fixed-schema advisory baseline.

    No pickle, executable artifact, remote download, shell, network, or connector is
    involved.  The fixture manifest is validated first and the deterministic scorer
    is the trusted loading boundary for this initial replay baseline.
    """

    method = LIGHTGBM_METHOD

    def __init__(self, manifest: LightGBMManifest) -> None:
        self.manifest = manifest

    @classmethod
    def from_fixture(cls, fixture: Mapping[str, Any]) -> LightGBMBaselineAdapter:
        manifest = LightGBMManifest.from_fixture(fixture)
        adapter = cls(manifest)
        events = fixture["events"]
        for index, event in enumerate(events):
            if not isinstance(event, Mapping):
                raise ValueError(f"LightGBM fixture event {index} must be an object")
            event_id = event.get("timeline_event_id")
            evidence_references = event.get("evidence_references")
            input_references = event.get("input_references")
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError(f"LightGBM fixture event {index} timeline_event_id is required")
            refs = _references(evidence_references, "evidence_references", required=True)
            inputs = _references(input_references, "input_references", required=True)
            if event_id not in inputs or not set(refs).issubset(set(inputs)):
                raise ValueError(f"LightGBM fixture event {index} input provenance is incomplete")
            expected = event.get("expected")
            if not isinstance(expected, Mapping):
                raise ValueError(f"LightGBM fixture event {index} expected output is required")
            feature_vector = event.get("feature_vector")
            result = adapter.predict(
                tenant_id=str(fixture["tenant_id"]),
                case_id=str(fixture["case_id"]),
                timeline_event_id=event_id,
                feature_vector=feature_vector,
                evidence_references=refs,
            )
            if (
                result.label.value != expected.get("label")
                or result.confidence != expected.get("confidence")
                or result.rationale != expected.get("rationale")
                or result.method != expected.get("method")
                or result.model_or_rules_version != expected.get("model_or_rules_version")
            ):
                raise ValueError(f"LightGBM fixture event {index} does not match the baseline")
        return adapter

    @classmethod
    def default(cls) -> LightGBMBaselineAdapter:
        return cls(baseline_manifest())

    @property
    def model_version(self) -> str:
        return self.manifest.model_version

    @property
    def feature_schema_version(self) -> str:
        return self.manifest.feature_schema_version

    @property
    def artifact_reference(self) -> str:
        return self.manifest.artifact_reference

    def predict(
        self,
        *,
        tenant_id: str,
        case_id: str,
        timeline_event_id: str,
        feature_vector: Mapping[str, Any],
        evidence_references: Sequence[str],
    ) -> AttributionSuggestion:
        _required_text(tenant_id, "tenant_id")
        _required_text(case_id, "case_id")
        timeline_event_id = _required_text(timeline_event_id, "timeline_event_id")
        if self.manifest.tenant_id is not None and tenant_id != self.manifest.tenant_id:
            raise ValueError("LightGBM prediction tenant does not match manifest")
        if self.manifest.case_id is not None and case_id != self.manifest.case_id:
            raise ValueError("LightGBM prediction case does not match manifest")
        references = _references(evidence_references, "evidence_references", required=True)
        vector = _validated_feature_vector(feature_vector, self.manifest.feature_order)
        label, confidence, rationale = _score(vector)
        return AttributionSuggestion(
            timeline_event_id=timeline_event_id,
            label=label,
            confidence=confidence,
            rationale=rationale,
            evidence_references=references,
            method=LIGHTGBM_METHOD,
            model_or_rules_version=self.manifest.model_version,
        )


def predict(
    *,
    tenant_id: str,
    case_id: str,
    timeline_event_id: str,
    feature_vector: Mapping[str, Any],
    evidence_references: Sequence[str],
) -> AttributionSuggestion:
    """Convenience prediction using the pinned built-in replay baseline."""

    return LightGBMBaselineAdapter.default().predict(
        tenant_id=tenant_id,
        case_id=case_id,
        timeline_event_id=timeline_event_id,
        feature_vector=feature_vector,
        evidence_references=evidence_references,
    )


def _validated_feature_vector(
    feature_vector: Mapping[str, Any], feature_order: tuple[str, ...]
) -> tuple[int, ...]:
    if not isinstance(feature_vector, Mapping):
        raise ValueError("LightGBM feature vector must be an object")
    if any(not isinstance(key, str) for key in feature_vector):
        raise ValueError("LightGBM feature names must be strings")
    keys = set(feature_vector)
    expected = set(feature_order)
    if keys != expected:
        missing = sorted(expected - keys)
        unsupported = sorted(keys - expected)
        raise ValueError(
            f"LightGBM feature schema mismatch; missing={missing}, unsupported={unsupported}"
        )
    values: list[int] = []
    for name in feature_order:
        value = feature_vector[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"LightGBM feature {name} must be a non-negative integer")
        if name in {"new_device", "profile_change_24h"} and value not in (0, 1):
            raise ValueError(f"LightGBM feature {name} must be binary")
        values.append(value)
    return tuple(values)


def _score(
    vector: tuple[int, ...],
) -> tuple[AttributionLabel, float, str]:
    (
        _payment_amount_minor,
        new_device,
        profile_change,
        session_velocity,
        successful_orders,
    ) = vector
    if new_device == 1 and profile_change == 1 and session_velocity >= 5 and successful_orders == 0:
        return (
            AttributionLabel.MALICIOUS,
            0.96,
            "The replay fixture combines a new device, a recent profile change, "
            "and high session velocity.",
        )
    if (
        new_device == 0
        and profile_change == 0
        and session_velocity <= 1
        and successful_orders >= 10
    ):
        return (
            AttributionLabel.LEGITIMATE,
            0.91,
            "The replay fixture matches an established customer pattern without "
            "recent account changes.",
        )
    return (
        AttributionLabel.UNCERTAIN,
        0.52,
        "The replay fixture contains a new device signal but insufficient "
        "corroboration for certainty.",
    )


def _references(value: object, name: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None:
        if required:
            raise ValueError(f"LightGBM {name} are required")
        return ()
    if isinstance(value, str | bytes):
        raise ValueError(f"LightGBM {name} must be a sequence")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"LightGBM {name} must be a sequence") from exc
    if required and not values:
        raise ValueError(f"LightGBM {name} are required")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"LightGBM {name} contain an invalid reference")
    return tuple(dict.fromkeys(item.strip() for item in values))


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"LightGBM {name} is required")
    return value.strip()


__all__ = [
    "LightGBMBaselineAdapter",
    "predict",
]
