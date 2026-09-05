"""Shared configuration guards used by hosted and local API assembly."""

from __future__ import annotations


def validate_fresh_agent_configuration(
    *,
    environment: str,
    live_financial_actions_enabled: bool,
    provider_available: bool,
) -> None:
    if live_financial_actions_enabled:
        raise ValueError("fresh agent cannot be enabled with live financial actions")
    if environment == "production" and not provider_available:
        raise ValueError("production fresh agent requires a trusted provider transport")
