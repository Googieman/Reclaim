"""T124 mode qualification and honest fallback coverage."""

from replay.mode_selection import ModeSelectionError, select_mode


def test_replay_is_structurally_simulated_even_when_dependencies_are_ready() -> None:
    result = select_mode(
        "replay",
        provider_available=True,
        connector_available=True,
        provider_qualified=True,
        connector_qualified=True,
        live_execution_occurred=True,
    )

    assert result.final_mode == "replay"
    assert result.effective_mode == "replay"
    assert result.live_execution_occurred is False
    assert "no merchant actions" in result.simulation_notice.lower()


def test_live_requires_observed_qualified_execution() -> None:
    result = select_mode(
        "live",
        provider_available=True,
        connector_available=True,
        provider_qualified=True,
        connector_qualified=True,
        live_execution_occurred=True,
    )

    assert result.final_mode == "live"
    assert result.effective_mode == "live"
    assert result.label == "live"


def test_unavailable_live_provider_falls_back_to_replay() -> None:
    result = select_mode("live")

    assert result.final_mode == "replay"
    assert result.effective_mode == "replay"
    assert result.fallback_reason
    assert result.live_execution_occurred is False


def test_unavailable_live_provider_can_escalate_explicitly() -> None:
    result = select_mode("live", fallback_policy="escalation")

    assert result.final_mode == "escalation"
    assert result.label == "unavailable"
    assert "escalation" in result.simulation_notice.lower()


def test_live_action_enablement_is_separate_from_live_mode() -> None:
    result = select_mode(
        "live",
        provider_available=True,
        connector_available=True,
        provider_qualified=True,
        connector_qualified=True,
        live_execution_occurred=True,
        live_actions_enabled=False,
        live_financial_actions_enabled=False,
    )

    assert result.final_mode == "live"
    assert result.live_actions_enabled is False
    assert result.live_financial_actions_enabled is False
    assert "disabled" in result.simulation_notice.lower()


def test_financial_action_enablement_cannot_bypass_live_action_gate() -> None:
    result = select_mode(
        "live",
        provider_available=True,
        connector_available=True,
        provider_qualified=True,
        connector_qualified=True,
        live_execution_occurred=True,
        live_actions_enabled=False,
        live_financial_actions_enabled=True,
    )

    assert result.final_mode == "live"
    assert result.live_actions_enabled is False
    assert result.live_financial_actions_enabled is False


def test_invalid_mode_and_fallback_are_rejected() -> None:
    try:
        select_mode("production")
    except ModeSelectionError as exc:
        assert "requested mode" in str(exc)
    else:  # pragma: no cover - assertion keeps the failure explicit
        raise AssertionError("invalid mode was accepted")

    try:
        select_mode("live", fallback_policy="live")
    except ModeSelectionError as exc:
        assert "fallback policy" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid fallback policy was accepted")
