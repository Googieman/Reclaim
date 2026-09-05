"""Allowlist-only network boundary for the Action Gateway.

The request contract contains connector identity, never a URL or host.  This
policy maps configured connector IDs to approved destinations owned by the
merchant; it does not perform network access itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


class NetworkPolicyError(ValueError):
    """Raised when a gateway connector is outside the configured egress policy."""


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    connector_destinations: Mapping[str, frozenset[str]]

    def __post_init__(self) -> None:
        normalized: dict[str, frozenset[str]] = {}
        for connector_id, destinations in self.connector_destinations.items():
            if not isinstance(connector_id, str) or not connector_id.strip():
                raise NetworkPolicyError("connector destination identity is required")
            if not isinstance(destinations, set | frozenset | tuple | list) or not destinations:
                raise NetworkPolicyError("each connector needs an approved destination")
            values = frozenset(
                destination
                for destination in destinations
                if isinstance(destination, str) and destination.strip()
            )
            if not values:
                raise NetworkPolicyError("approved destinations cannot be blank")
            if any(
                any(character in destination for character in ("/", "\\", ":", "?", "#", "@"))
                or any(character.isspace() for character in destination)
                for destination in values
            ):
                raise NetworkPolicyError(
                    "network policy destinations must be configured host names"
                )
            normalized[connector_id.strip()] = values
        object.__setattr__(self, "connector_destinations", MappingProxyType(normalized))

    def allows(self, *, connector_id: str, destination: str | None = None) -> bool:
        approved = self.connector_destinations.get(connector_id)
        if approved is None:
            return False
        return destination is None or destination in approved

    def require(self, *, connector_id: str, destination: str | None = None) -> None:
        if not self.allows(connector_id=connector_id, destination=destination):
            raise NetworkPolicyError(
                "connector destination is outside the Action Gateway egress allowlist"
            )


class ActionNetworkBoundary:
    """Resolve a connector only when its configured identity is allowlisted."""

    def __init__(self, policy: NetworkPolicy) -> None:
        self.policy = policy

    def authorize_connector(self, connector_id: str) -> None:
        self.policy.require(connector_id=connector_id)


def build_default_network_policy(connector_ids: Iterable[str]) -> NetworkPolicy:
    """Create an identity-only simulator policy with no caller-selected host."""

    return NetworkPolicy(
        {connector_id: frozenset({"merchant-controlled"}) for connector_id in connector_ids}
    )


__all__ = [
    "ActionNetworkBoundary",
    "NetworkPolicy",
    "NetworkPolicyError",
    "build_default_network_policy",
]
