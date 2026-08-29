import pytest

from packages.contracts.intake import IncidentIntakeRequest
from packages.contracts.schema_registry import (
    SchemaDefinition,
    SchemaRegistry,
    is_compatible,
    parse_version,
)


def test_schema_registry_accepts_supported_versions_and_exposes_owned_models() -> None:
    registry = SchemaRegistry(
        [SchemaDefinition(name="incident-intake", model=IncidentIntakeRequest)]
    )
    assert registry.names() == ("incident-intake",)
    assert registry.get("incident-intake").model is IncidentIntakeRequest
    assert is_compatible("1.0") is True
    assert is_compatible("2.0.0") is False
    assert parse_version("v1.2") == (1, 2, 0)


def test_schema_registry_rejects_duplicate_or_incompatible_definitions() -> None:
    definition = SchemaDefinition(name="incident-intake", model=IncidentIntakeRequest)
    registry = SchemaRegistry([definition])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(definition)
    with pytest.raises(ValueError, match="incompatible"):
        registry.register(
            SchemaDefinition(name="future", model=IncidentIntakeRequest, version="2.0.0")
        )
