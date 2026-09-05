"""Authoritative LIVE/REPLAY mode qualification.

Mode selection is deliberately a pure boundary.  It observes server-side
qualification facts and returns a serializable decision for the demo API and
operator UI.  Client configuration cannot promote a replay result to LIVE.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Literal

RequestedMode = Literal["live", "replay"]
EffectiveMode = Literal["live", "replay"]
FinalMode = Literal["live", "replay", "escalation"]
FallbackPolicy = Literal["replay", "escalation"]


class ModeSelectionError(ValueError):
    """Raised when a mode request or server qualification fact is invalid."""


@dataclass(frozen=True, slots=True)
class ModeSelectionInput:
    """Server-observed facts used to qualify a requested run mode."""

    requested_mode: RequestedMode = "replay"
    provider_available: bool = False
    connector_available: bool = False
    provider_qualified: bool = False
    connector_qualified: bool = False
    live_execution_occurred: bool = False
    live_actions_enabled: bool = False
    live_financial_actions_enabled: bool = False
    fallback_policy: FallbackPolicy = "replay"


@dataclass(frozen=True, slots=True)
class ModeSelection:
    """Truthful mode state exposed to the API and presentation layer."""

    requested_mode: RequestedMode
    effective_mode: EffectiveMode
    final_mode: FinalMode
    provider_available: bool
    connector_available: bool
    provider_qualified: bool
    connector_qualified: bool
    live_execution_occurred: bool
    live_actions_enabled: bool
    live_financial_actions_enabled: bool
    availability_reasons: tuple[str, ...]
    fallback_reason: str | None
    label: str
    simulation_notice: str
    decision_version: str = "mode-selection-v1.0.0"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe response without exposing credentials or secrets."""

        return asdict(self)


def select_mode(
    requested_mode: str = "replay",
    *,
    provider_available: bool = False,
    connector_available: bool = False,
    provider_qualified: bool = False,
    connector_qualified: bool = False,
    live_execution_occurred: bool = False,
    live_actions_enabled: bool = False,
    live_financial_actions_enabled: bool = False,
    fallback_policy: str = "replay",
) -> ModeSelection:
    """Select a mode using only server-observed qualification facts.

    A LIVE response requires an explicitly qualified provider and connector and
    an observed live execution.  Otherwise the result is REPLAY or an explicit
    escalation according to the server fallback policy.
    """

    requested = _requested_mode(requested_mode)
    fallback = _fallback_policy(fallback_policy)
    facts = ModeSelectionInput(
        requested_mode=requested,
        provider_available=bool(provider_available),
        connector_available=bool(connector_available),
        provider_qualified=bool(provider_qualified),
        connector_qualified=bool(connector_qualified),
        live_execution_occurred=bool(live_execution_occurred),
        live_actions_enabled=bool(live_actions_enabled),
        live_financial_actions_enabled=bool(
            live_financial_actions_enabled and live_actions_enabled
        ),
        fallback_policy=fallback,
    )

    if requested == "replay":
        return ModeSelection(
            requested_mode="replay",
            effective_mode="replay",
            final_mode="replay",
            provider_available=facts.provider_available,
            connector_available=facts.connector_available,
            provider_qualified=facts.provider_qualified,
            connector_qualified=facts.connector_qualified,
            live_execution_occurred=False,
            live_actions_enabled=False,
            live_financial_actions_enabled=False,
            availability_reasons=("replay was explicitly requested",),
            fallback_reason=None,
            label="replay",
            simulation_notice="REPLAY — simulation / no merchant actions",
        )

    reasons = _qualification_reasons(facts)
    if not reasons:
        return ModeSelection(
            requested_mode="live",
            effective_mode="live",
            final_mode="live",
            provider_available=True,
            connector_available=True,
            provider_qualified=True,
            connector_qualified=True,
            live_execution_occurred=True,
            live_actions_enabled=facts.live_actions_enabled,
            live_financial_actions_enabled=facts.live_financial_actions_enabled,
            availability_reasons=("provider and connector are qualified",),
            fallback_reason=None,
            label="live",
            simulation_notice=(
                "LIVE — qualified run; live actions disabled"
                if not facts.live_actions_enabled
                else "LIVE — qualified run; action enablement is separately governed"
            ),
        )

    fallback_reason = "; ".join(reasons)
    if fallback == "escalation":
        return ModeSelection(
            requested_mode="live",
            effective_mode="replay",
            final_mode="escalation",
            provider_available=facts.provider_available,
            connector_available=facts.connector_available,
            provider_qualified=facts.provider_qualified,
            connector_qualified=facts.connector_qualified,
            live_execution_occurred=False,
            live_actions_enabled=False,
            live_financial_actions_enabled=False,
            availability_reasons=tuple(reasons),
            fallback_reason=fallback_reason,
            label="unavailable",
            simulation_notice=("UNAVAILABLE — live qualification failed; escalation required"),
        )
    return ModeSelection(
        requested_mode="live",
        effective_mode="replay",
        final_mode="replay",
        provider_available=facts.provider_available,
        connector_available=facts.connector_available,
        provider_qualified=facts.provider_qualified,
        connector_qualified=facts.connector_qualified,
        live_execution_occurred=False,
        live_actions_enabled=False,
        live_financial_actions_enabled=False,
        availability_reasons=tuple(reasons),
        fallback_reason=fallback_reason,
        label="replay",
        simulation_notice="REPLAY — live provider unavailable; simulation / no merchant actions",
    )


def select_mode_from_environment(*, requested_mode: str | None = None) -> ModeSelection:
    """Build a mode decision from server environment, with safe replay defaults."""

    return select_mode(
        requested_mode or os.getenv("RECLAIM_RUN_MODE", "replay"),
        provider_available=_env_bool("RECLAIM_PROVIDER_AVAILABLE"),
        connector_available=_env_bool("RECLAIM_CONNECTOR_AVAILABLE"),
        provider_qualified=_env_bool("RECLAIM_PROVIDER_QUALIFIED"),
        connector_qualified=_env_bool("RECLAIM_CONNECTOR_QUALIFIED"),
        live_execution_occurred=_env_bool("RECLAIM_LIVE_EXECUTION_OCCURRED"),
        live_actions_enabled=_env_bool("RECLAIM_LIVE_ACTIONS_ENABLED"),
        live_financial_actions_enabled=_env_bool("RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED"),
        fallback_policy=os.getenv(
            "RECLAIM_PROVIDER_UNAVAILABILITY_POLICY",
            os.getenv("RECLAIM_MODE_FALLBACK", "replay"),
        ),
    )


def _qualification_reasons(facts: ModeSelectionInput) -> list[str]:
    reasons: list[str] = []
    if not facts.provider_available:
        reasons.append("model provider is unavailable")
    if not facts.connector_available:
        reasons.append("evidence/action connector is unavailable")
    if not facts.provider_qualified:
        reasons.append("model provider is not qualified for live execution")
    if not facts.connector_qualified:
        reasons.append("connector is not qualified for live execution")
    if not facts.live_execution_occurred:
        reasons.append("no explicitly observed live execution is present")
    return reasons


def _requested_mode(value: str) -> RequestedMode:
    normalized = str(value).strip().lower()
    if normalized not in {"live", "replay"}:
        raise ModeSelectionError("requested mode must be live or replay")
    return normalized  # type: ignore[return-value]


def _fallback_policy(value: str) -> FallbackPolicy:
    normalized = str(value).strip().lower()
    if normalized not in {"replay", "escalation"}:
        raise ModeSelectionError("fallback policy must be replay or escalation")
    return normalized  # type: ignore[return-value]


def _env_bool(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ModeSelection",
    "ModeSelectionError",
    "ModeSelectionInput",
    "select_mode",
    "select_mode_from_environment",
]
