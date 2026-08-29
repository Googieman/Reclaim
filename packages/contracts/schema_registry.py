"""Schema ownership and compatibility metadata for shared contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from .common import CONTRACT_VERSION

_VERSION_RE = re.compile(r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)(?:\.(?P<patch>0|[1-9]\d*))?$")
ModelT = TypeVar("ModelT", bound=type[BaseModel])


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse the supported ``major.minor[.patch]`` contract version form."""

    match = _VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError(f"invalid contract version: {version!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )


def is_compatible(declared: str, supported: str = CONTRACT_VERSION) -> bool:
    """Return whether a declared schema can be consumed by the supported version."""

    declared_parts = parse_version(declared)
    supported_parts = parse_version(supported)
    return declared_parts[0] == supported_parts[0] and declared_parts <= supported_parts


@dataclass(frozen=True)
class SchemaDefinition:
    """Immutable registry metadata for one shared schema."""

    name: str
    model: type[BaseModel]
    version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("schema name cannot be blank")
        parse_version(self.version)


class SchemaRegistry:
    """In-process registry of owned schemas and their compatible versions."""

    def __init__(self, definitions: Iterable[SchemaDefinition] = ()) -> None:
        self._definitions: dict[str, SchemaDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: SchemaDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"schema already registered: {definition.name}")
        if not is_compatible(definition.version):
            raise ValueError(f"schema version is incompatible: {definition.version}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> SchemaDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"unknown schema: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    @staticmethod
    def is_compatible(declared: str, supported: str = CONTRACT_VERSION) -> bool:
        return is_compatible(declared, supported)
