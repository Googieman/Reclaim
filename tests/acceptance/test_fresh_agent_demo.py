"""Safe demo acceptance for fresh execution alongside deterministic replay."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from api.main import create_app
from app.config import Settings
from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)
from agent.litellm_gateway import LiteLLMProviderAdapter


TENANT = "tenant-canonical-demo"
CASE = "case-canonical-demo-001"


def _request_factory(
    tenant_id: str, case_id: str, budget: ModelBudget
) -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id=tenant_id,
        correlation_id="correlation-fresh-demo",
        case_id=case_id,
        redacted_case_representation={
            "timeline": [
                {"timeline_event_id": "timeline-demo"},
                {"timeline_event_id": "timeline-demo-2"},
            ],
            "evidence": [
                {"evidence_id": "evidence-demo"},
                {"evidence_id": "evidence-demo-2"},
            ],
            "uncertainty": [],
        },
        evidence_references=("evidence-demo", "evidence-demo-2"),
        allowed_tools=(),
        policy_version_id="policy-v1.0.0",
        budget=budget,
        provider_mode=ProviderMode.LIVE,
        replay_label=ProviderMode.LIVE,
    )


def _completion(**_: Any) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "analysis_id": "analysis-fresh-demo",
                            "provider": "demo-provider",
                            "model": "demo-model",
                            "tenant_id": TENANT,
                            "case_id": CASE,
                            "correlation_id": "correlation-fresh-demo",
                            "attributions": [],
                            "proposals": [],
                            "uncertainty": "No model uncertainty beyond bounded review.",
                            "refusal_records": [],
                        }
                    )
                }
            }
        ]
    }


def _mixed_completion(**_: Any) -> dict[str, Any]:
    payload = json.loads(_completion()["choices"][0]["message"]["content"])
    payload["attributions"] = [
        {
            "timeline_event_id": "timeline-demo",
            "label": "malicious",
            "confidence": 0.9,
            "rationale": "Bounded evidence indicates suspicious activity.",
            "evidence_references": ["evidence-demo"],
            "method": "specialist",
            "model_or_rules_version": "specialist-v1",
        },
        {
            "timeline_event_id": "timeline-demo-2",
            "label": "legitimate",
            "confidence": 0.8,
            "rationale": "The bounded event is consistent with legitimate activity.",
            "evidence_references": ["evidence-demo-2"],
            "method": "specialist",
            "model_or_rules_version": "specialist-v1",
        },
    ]
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def _uncertain_completion(**_: Any) -> dict[str, Any]:
    payload = json.loads(_completion()["choices"][0]["message"]["content"])
    payload["attributions"] = [
        {
            "timeline_event_id": "timeline-demo",
            "label": "uncertain",
            "confidence": 0.4,
            "rationale": "Conflicting bounded evidence requires human review.",
            "evidence_references": ["evidence-demo"],
            "method": "specialist",
            "model_or_rules_version": "specialist-v1",
        }
    ]
    payload["uncertainty"] = "Conflicting evidence requires human review."
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def test_fresh_and_replay_are_distinct_safe_paths() -> None:
    provider = LiteLLMProviderAdapter(
        provider="demo-provider",
        model="demo-model",
        mode=ProviderMode.LIVE,
        completion=_completion,
    )
    settings = Settings(
        tenant_id=TENANT,
        demo_read_only_enabled=True,
        fresh_agent_enabled=True,
    )
    with TestClient(
        create_app(
            settings=settings,
            agent_provider=provider,
            agent_request_factory=_request_factory,
        )
    ) as client:
        fresh = client.post(f"/tenants/{TENANT}/cases/{CASE}/agent-runs", json={})
        fresh_run_id = fresh.json()["run_id"]
        cross_tenant_read = client.get(
            f"/tenants/another-tenant/cases/{CASE}/agent-runs/{fresh_run_id}"
        )
        replay = client.post(
            f"/tenants/{TENANT}/cases/{CASE}/replay",
            json={"case_id": CASE, "deterministic_seed": 0},
        )

    assert fresh.status_code == 200
    assert fresh.json()["execution_mode"] == "fresh_agent"
    assert fresh.json()["provider_mode"] == "live"
    assert fresh.json()["remote_side_effects"] == []
    assert cross_tenant_read.status_code == 404
    assert replay.status_code == 200
    assert replay.json()["mode"] == "replay"
    assert replay.json()["remote_side_effects"] == []


def test_fresh_demo_covers_mixed_attribution_and_explicit_provider_failure() -> None:
    mixed_provider = LiteLLMProviderAdapter(
        provider="demo-provider",
        model="demo-model",
        mode=ProviderMode.LIVE,
        completion=_mixed_completion,
    )
    with TestClient(
        create_app(
            settings=Settings(tenant_id=TENANT, fresh_agent_enabled=True),
            agent_provider=mixed_provider,
            agent_request_factory=_request_factory,
        )
    ) as client:
        mixed = client.post(f"/tenants/{TENANT}/cases/{CASE}/agent-runs", json={})

    failed_provider = LiteLLMProviderAdapter(
        provider="demo-provider",
        model="demo-model",
        mode=ProviderMode.LIVE,
        completion=lambda **_: (_ for _ in ()).throw(TimeoutError()),
    )
    with TestClient(
        create_app(
            settings=Settings(tenant_id=TENANT, fresh_agent_enabled=True),
            agent_provider=failed_provider,
            agent_request_factory=_request_factory,
        )
    ) as client:
        failed = client.post(f"/tenants/{TENANT}/cases/{CASE}/agent-runs", json={})

    assert mixed.status_code == 200
    assert {item["label"] for item in mixed.json()["analysis"]["attributions"]} == {
        "malicious",
        "legitimate",
    }
    assert failed.status_code == 503
    assert failed.json()["status"] == "unavailable"
    assert failed.json()["execution_mode"] == "fresh_agent"
    assert failed.json()["remote_side_effects"] == []


def test_fresh_demo_preserves_uncertain_attribution_without_action() -> None:
    provider = LiteLLMProviderAdapter(
        provider="demo-provider",
        model="demo-model",
        mode=ProviderMode.LIVE,
        completion=_uncertain_completion,
    )
    with TestClient(
        create_app(
            settings=Settings(tenant_id=TENANT, fresh_agent_enabled=True),
            agent_provider=provider,
            agent_request_factory=_request_factory,
        )
    ) as client:
        response = client.post(f"/tenants/{TENANT}/cases/{CASE}/agent-runs", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["attributions"][0]["label"] == "uncertain"
    assert body["analysis"]["proposals"] == []
    assert body["remote_side_effects"] == []
