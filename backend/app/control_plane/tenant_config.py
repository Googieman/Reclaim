"""Centrally bounded tenant configuration declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TenantConfigurationSource(Protocol):
    def load(self, tenant_id: str) -> TenantConfiguration: ...


@dataclass(frozen=True, slots=True)
class TenantConfiguration:
    tenant_id: str
    connector_ids: frozenset[str]
    policy_version_id: str
    max_model_budget_tokens: int = 16_000
    live_actions_enabled: bool = False
    live_financial_actions_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.policy_version_id.strip():
            raise ValueError("tenant configuration requires tenant and policy version")
        if self.max_model_budget_tokens < 1 or self.max_model_budget_tokens > 100_000:
            raise ValueError("model budget exceeds central safety bound")
        if self.live_actions_enabled or self.live_financial_actions_enabled:
            raise ValueError("live actions are not qualified and must remain disabled")


class TenantConfigurationBoundary:
    """Read configuration declarations; never returns credentials or runtime clients."""

    def __init__(self, source: TenantConfigurationSource) -> None:
        self.source = source

    def get(self, tenant_id: str) -> TenantConfiguration:
        configuration = self.source.load(tenant_id)
        if configuration.tenant_id != tenant_id:
            raise ValueError("configuration source crossed tenant boundary")
        return configuration

    def connector_enabled(self, *, tenant_id: str, connector_id: str) -> bool:
        return connector_id in self.get(tenant_id).connector_ids

    def action_mode(self, tenant_id: str) -> str:
        configuration = self.get(tenant_id)
        if configuration.live_financial_actions_enabled:
            return "live-financial"
        if configuration.live_actions_enabled:
            return "live-reversible"
        return "replay"


class StaticTenantConfigurationSource:
    """Small declaration source for tests/bootstrap; production uses PostgreSQL-backed reads."""

    def __init__(self, configurations: list[TenantConfiguration]) -> None:
        self._configurations = {
            configuration.tenant_id: configuration for configuration in configurations
        }

    def load(self, tenant_id: str) -> TenantConfiguration:
        try:
            return self._configurations[tenant_id]
        except KeyError as exc:
            raise KeyError("tenant configuration is not registered") from exc
