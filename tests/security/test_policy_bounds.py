"""T080 centrally bounded tenant-policy configuration tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.control_plane.registry import PolicyOwnerRegistry
from app.control_plane.tenant_config import (
    StaticTenantConfigurationSource,
    TenantConfiguration,
    TenantConfigurationBoundary,
)
from app.config import Settings
from us3_test_seams import require_symbol


def test_valid_tenant_configuration_is_replay_only_by_default() -> None:
    configuration = TenantConfiguration(
        tenant_id="tenant-us3-policy",
        connector_ids=frozenset({"session-actions"}),
        policy_version_id="policy-us3-v1.0.0",
    )
    boundary = TenantConfigurationBoundary(
        StaticTenantConfigurationSource([configuration])
    )

    assert boundary.get("tenant-us3-policy") == configuration
    assert (
        boundary.connector_enabled(
            tenant_id="tenant-us3-policy", connector_id="session-actions"
        )
        is True
    )
    assert boundary.action_mode("tenant-us3-policy") == "replay"
    assert configuration.live_actions_enabled is False
    assert configuration.live_financial_actions_enabled is False


@pytest.mark.parametrize("budget", (0, 100_001))
def test_existing_central_model_budget_bound_fails_closed(budget: int) -> None:
    with pytest.raises(ValueError, match="central safety bound"):
        TenantConfiguration(
            tenant_id="tenant-us3-policy",
            connector_ids=frozenset(),
            policy_version_id="policy-us3-v1.0.0",
            max_model_budget_tokens=budget,
        )


def test_financial_actions_cannot_be_enabled_without_live_actions() -> None:
    with pytest.raises(ValueError, match="live actions"):
        TenantConfiguration(
            tenant_id="tenant-us3-policy",
            connector_ids=frozenset(),
            policy_version_id="policy-us3-v1.0.0",
            live_financial_actions_enabled=True,
        )


def test_policy_owner_registry_does_not_grant_ordinary_reviewer_policy_owner_access() -> (
    None
):
    owners = PolicyOwnerRegistry()
    owners.register(tenant_id="tenant-us3-policy", subjects=("policy-owner-1",))

    assert (
        owners.is_owner(tenant_id="tenant-us3-policy", subject="policy-owner-1") is True
    )
    assert owners.is_owner(tenant_id="tenant-us3-policy", subject="reviewer-1") is False
    assert owners.is_owner(tenant_id="tenant-other", subject="policy-owner-1") is False


def test_settings_keep_live_financial_execution_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.live_actions_enabled is False
    assert settings.live_financial_actions_enabled is False
    assert settings.run_mode == "replay"


@pytest.mark.xfail(
    strict=True,
    reason="Expected-red owner T089: bounded tenant policy configuration/change control",
)
def test_tenant_policy_thresholds_and_denied_changes_are_bounded_and_auditable() -> (
    None
):
    validator = require_symbol(
        "policy.tenant_configuration",
        "validate_tenant_policy_configuration",
        task="T080 -> T089",
    )
    cases: tuple[tuple[str, dict[str, Any], bool], ...] = (
        (
            "valid",
            {
                "thresholds": {"auto_revoke_confidence": 0.95},
                "actor_role": "policy-owner",
            },
            True,
        ),
        (
            "below-central-bound",
            {
                "thresholds": {"auto_revoke_confidence": 0.10},
                "actor_role": "policy-owner",
            },
            False,
        ),
        (
            "above-central-bound",
            {
                "thresholds": {"auto_revoke_confidence": 1.01},
                "actor_role": "policy-owner",
            },
            False,
        ),
        (
            "model-threshold-change",
            {"thresholds": {"auto_revoke_confidence": 0.99}, "actor_role": "model"},
            False,
        ),
        (
            "reviewer-threshold-change",
            {"thresholds": {"auto_revoke_confidence": 0.99}, "actor_role": "reviewer"},
            False,
        ),
        (
            "unsupported-field",
            {"thresholds": {"arbitrary_network": True}, "actor_role": "policy-owner"},
            False,
        ),
        (
            "malformed",
            {"thresholds": "not-an-object", "actor_role": "policy-owner"},
            False,
        ),
    )
    for name, payload, accepted in cases:
        result = validator(tenant_id="tenant-us3-policy", change=name, **payload)
        assert result.accepted is accepted
        if not accepted:
            assert result.audit_reference
