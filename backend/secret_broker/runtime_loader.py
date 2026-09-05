"""Translate a trusted bundle into private process configuration."""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import SecretBundle


class RuntimeSecretLoader:
    """Keep broker values in trusted service memory and map only named fields."""

    def environment(self, bundle: SecretBundle, field_mapping: Mapping[str, str]) -> dict[str, str]:
        unknown_fields = set(bundle.values) - set(field_mapping)
        if unknown_fields:
            raise ValueError("secret bundle contains an unmapped field")
        missing_fields = set(field_mapping) - set(bundle.values)
        if missing_fields:
            raise ValueError("secret bundle is missing a required field")
        return {
            target: bundle.values[source].get_secret_value()
            for source, target in field_mapping.items()
        }
