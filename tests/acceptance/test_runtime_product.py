"""Acceptance coverage for the assembled, safe REPLAY product runtime."""

from __future__ import annotations

import pytest
from api.main import create_app
from app.config import Settings
from app.local_runtime import LocalDemoRuntime
from fastapi.testclient import TestClient
from replay.variants import run_variant

CANONICAL_TENANT = "tenant-canonical-demo"
CANONICAL_CASE = "case-canonical-demo-001"


class _EvidenceCapture:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_or_get(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class _UnitOfWorkCapture:
    def __init__(self) -> None:
        self.evidence = _EvidenceCapture()


def _demo_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "development",
        "tenant_id": CANONICAL_TENANT,
        "run_mode": "replay",
        "replay_label": "replay",
        "live_actions_enabled": False,
        "live_financial_actions_enabled": False,
        "demo_read_only_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("flag", ["live_actions_enabled", "live_financial_actions_enabled"])
def test_read_only_demo_settings_keep_stable_guard_for_live_flags(flag: str) -> None:
    with pytest.raises(ValueError, match="read-only demo"):
        _demo_settings(**{flag: True})


def test_local_seed_scopes_fixture_evidence_identity_to_case() -> None:
    uow = _UnitOfWorkCapture()
    source = {
        "evidence": [
            {
                "evidence_id": "evidence-session-001",
                "connector_id": "session-simulator-v1.0.0",
                "provider_identifier": "session-canonical-001",
                "source_identity": "session-simulator",
                "raw_checksum": "sha256:canonical-session-001",
                "completeness": "complete",
            }
        ]
    }

    identifiers = LocalDemoRuntime._seed_evidence(uow, source, "case-recovery-001")

    assert identifiers == {"evidence-session-001": "evidence-session-001:case-recovery-001"}
    assert uow.evidence.calls[0]["source_identifier"] == "session-canonical-001:case-recovery-001"


def test_assembled_runtime_serves_health_mode_replay_and_operator_view() -> None:
    with TestClient(create_app(settings=_demo_settings())) as client:
        assert client.get("/health/live").json() == {
            "status": "live",
            "service": "reclaim-api",
        }

        readiness = client.get("/health/ready")
        assert readiness.status_code == 200
        assert readiness.json()["mode"] == "replay"
        assert readiness.json()["live_actions_enabled"] is False

        mode = client.get(f"/tenants/{CANONICAL_TENANT}/demo/mode")
        assert mode.status_code == 200
        assert mode.json()["final_mode"] == "replay"
        assert mode.json()["live_execution_occurred"] is False

        response = client.get(f"/tenants/{CANONICAL_TENANT}/cases/{CANONICAL_CASE}/operator-view")
        assert response.status_code == 200
        view = response.json()
        assert view["case"]["case_id"] == CANONICAL_CASE
        assert view["case"]["tenant_id"] == CANONICAL_TENANT
        assert view["mode"]["final_mode"] == "replay"
        assert view["evaluation"]["label"] == "replay"
        assert view["read_only"] is True
        assert view["authoritative"] is False
        assert view["remote_side_effects"] == []
        assert len(view["timeline"]) == 4
        assert len(view["audit"]) == 13
        assert view["exposure"]["gross_exposure_minor"] == 30_000

        replay = client.post(
            f"/tenants/{CANONICAL_TENANT}/cases/{CANONICAL_CASE}/replay",
            json={"case_id": CANONICAL_CASE, "deterministic_seed": 0},
        )
        assert replay.status_code == 200
        assert replay.json()["side_effects"] is False
        assert replay.json()["remote_side_effects"] == []


@pytest.mark.parametrize(
    ("tenant_id", "case_id"),
    [
        ("another-tenant", CANONICAL_CASE),
        (CANONICAL_TENANT, "another-case"),
    ],
)
def test_demo_operator_view_rejects_unknown_scope(tenant_id: str, case_id: str) -> None:
    response = TestClient(create_app(settings=_demo_settings())).get(
        f"/tenants/{tenant_id}/cases/{case_id}/operator-view"
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "unsafe",
    [
        {"run_mode": "live"},
        {"live_actions_enabled": True},
        {"live_financial_actions_enabled": True},
        {"environment": "production"},
    ],
)
def test_read_only_demo_configuration_fails_closed(unsafe: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="read-only demo"):
        create_app(settings=_demo_settings(**unsafe))


@pytest.mark.parametrize(
    ("variant", "path", "expected", "terminal"),
    [
        (
            "policy_denial",
            ("policy_decision", "result"),
            "deny",
            "escalated_unresolved",
        ),
        (
            "approval_rejected",
            ("approval", "status"),
            "rejected",
            "escalated_unresolved",
        ),
        ("approval_expired", ("approval", "status"), "expired", "escalated_unresolved"),
        (
            "verification_failure",
            ("verification", "approval_gated_action"),
            "verified_failure",
            "verified_failed",
        ),
        (
            "inconclusive_verification",
            ("verification", "approval_gated_action"),
            "inconclusive",
            "escalated_unresolved",
        ),
    ],
)
def test_replay_variants_are_internally_coherent(
    variant: str, path: tuple[str, str], expected: str, terminal: str
) -> None:
    result = run_variant(variant=variant, deterministic_seed=0, mode="replay")

    assert result[path[0]][path[1]] == expected
    assert result["terminal_state"] == terminal
    assert result["replay_run"]["terminal_state"] == terminal
    assert result["side_effects"] is False
    assert not result["remote_side_effects"]
