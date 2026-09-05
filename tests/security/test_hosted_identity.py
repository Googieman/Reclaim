"""Production fresh-agent and tenant identity construction checks."""

from __future__ import annotations

import pytest

from app.api_compat import validate_fresh_agent_configuration


def test_production_fresh_agent_requires_trusted_provider_transport() -> None:
    with pytest.raises(ValueError, match="trusted provider"):
        validate_fresh_agent_configuration(
            environment="production", live_financial_actions_enabled=False, provider_available=False
        )

    validate_fresh_agent_configuration(
        environment="production", live_financial_actions_enabled=False, provider_available=True
    )
