"""Contract coverage for advisory rules and LightGBM attribution outputs."""

import pytest
from pydantic import ValidationError

from packages.contracts.analysis_policy import AttributionLabel, AttributionSuggestion


def make_attribution(**overrides: object) -> AttributionSuggestion:
    values: dict[str, object] = {
        "timeline_event_id": "timeline-event-1",
        "label": AttributionLabel.MALICIOUS,
        "confidence": 0.875,
        "rationale": "The event matches the configured attribution signals.",
        "evidence_references": ("evidence-1", "evidence-2"),
        "method": "rules",
        "model_or_rules_version": "rules-v1.0.0",
    }
    values.update(overrides)
    return AttributionSuggestion(**values)


@pytest.mark.parametrize(
    ("method", "version"),
    (
        ("rules", "rules-v1.0.0"),
        ("lightgbm", "lightgbm-baseline-v1.0.0"),
    ),
)
def test_rules_and_lightgbm_outputs_retain_input_and_provenance_fields(
    method: str, version: str
) -> None:
    result = make_attribution(method=method, model_or_rules_version=version)

    assert result.timeline_event_id == "timeline-event-1"
    assert result.evidence_references == ("evidence-1", "evidence-2")
    assert result.method == method
    assert result.model_or_rules_version == version
    assert result.label is AttributionLabel.MALICIOUS
    assert result.confidence == 0.875
    assert result.rationale == "The event matches the configured attribution signals."

    restored = AttributionSuggestion.model_validate(result.model_dump())
    assert restored == result


def test_attribution_labels_remain_distinct() -> None:
    results = tuple(
        make_attribution(label=label, timeline_event_id=f"timeline-{label.value}")
        for label in AttributionLabel
    )

    assert {result.label for result in results} == {
        AttributionLabel.MALICIOUS,
        AttributionLabel.LEGITIMATE,
        AttributionLabel.UNCERTAIN,
    }
    assert len({result.label.value for result in results}) == 3


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("label", "suspicious"),
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("rationale", ""),
    ),
)
def test_attribution_rejects_malformed_output(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_attribution(**{field: value})


def test_attribution_rejects_uncontracted_fields() -> None:
    with pytest.raises(ValidationError):
        make_attribution(unsupported_claim="not evidence-backed")
