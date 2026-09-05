"""Static integration gate for the checked-in n8n workflow definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "infra" / "n8n" / "workflows"


def _workflow(name: str) -> dict:
    return json.loads((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def _nodes_by_name(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in workflow["nodes"]}


def _http_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest"]


def _successors(
    workflow: dict[str, Any],
    node_name: str,
    output_index: int = 0,
) -> list[str]:
    edges = workflow["connections"].get(node_name, {}).get("main", [])
    if output_index >= len(edges):
        return []
    return [edge["node"] for edge in edges[output_index]]


def test_incident_handoff_has_kafka_trigger_idempotent_claim_and_owner_gate() -> None:
    workflow = _workflow("incident-analysis-handoff.v1.json")
    nodes = _nodes_by_name(workflow)
    node_types = {node["type"] for node in workflow["nodes"]}

    assert "n8n-nodes-base.kafkaTrigger" in node_types
    assert "Filter incident.accepted" in nodes
    assert "Execution owns run" in nodes
    assert nodes["Execution owns run"]["type"] == "n8n-nodes-base.if"
    assert "Typed AI analysis" in nodes
    assert "Record human handoff" in nodes
    assert workflow["settings"]["errorWorkflow"] == "incident-analysis-error-recovery.v1"
    assert "Claim n8n execution" in workflow["connections"]
    assert workflow["connections"]["Execution owns run"]["main"][1] == []
    claim_body = nodes["Claim n8n execution"]["parameters"]["jsonBody"]
    assert "expected_state" in claim_body


def test_incident_handoff_kafka_trigger_uses_n8n_group_id_parameter() -> None:
    workflow = _workflow("incident-analysis-handoff.v1.json")
    trigger = _nodes_by_name(workflow)["Incident accepted"]
    parameters = trigger["parameters"]

    assert parameters["topic"] == "reclaim.domain.v1"
    assert "topics" not in parameters
    assert parameters["groupId"] == "reclaim-n8n-incident-analysis-v1"
    assert "consumerGroupId" not in parameters
    assert parameters["options"]["jsonParseMessage"] is True
    assert parameters["options"]["onlyMessage"] is True


def test_all_reclaim_http_nodes_use_finite_retry_settings() -> None:
    workflows = (
        _workflow("incident-analysis-handoff.v1.json"),
        _workflow("incident-analysis-error-recovery.v1.json"),
    )

    for workflow in workflows:
        for node in _http_nodes(workflow):
            assert node.get("retryOnFail") is True, node["name"]
            assert isinstance(node.get("maxTries"), int), node["name"]
            assert 1 < node["maxTries"] <= 5, node["name"]
            assert isinstance(node.get("waitBetweenTries"), int), node["name"]
            assert 0 < node["waitBetweenTries"] <= 5000, node["name"]


def test_handoff_analysis_outcomes_are_explicitly_split_between_success_and_attention() -> None:
    workflow = _workflow("incident-analysis-handoff.v1.json")
    nodes = _nodes_by_name(workflow)

    assert _successors(workflow, "Typed AI analysis") == ["Analysis completed?"]
    assert nodes["Analysis completed?"]["type"] == "n8n-nodes-base.if"
    completed_check = nodes["Analysis completed?"]["parameters"]["conditions"]["conditions"][0]
    assert completed_check["leftValue"] == "={{$json.status}}"
    assert completed_check["rightValue"] == "completed"
    assert _successors(workflow, "Analysis completed?", 0) == ["Record analysis and policy"]
    assert _successors(workflow, "Analysis completed?", 1) == ["Record requires_attention"]
    assert _successors(workflow, "Record analysis and policy") == ["Record human handoff"]
    assert _successors(workflow, "Record requires_attention") == []


def test_agent_analysis_http_preserves_non_2xx_unavailable_body_for_recovery_branch() -> None:
    workflow = _workflow("incident-analysis-handoff.v1.json")
    analysis = _nodes_by_name(workflow)["Typed AI analysis"]
    response_options = (
        analysis["parameters"].get("options", {}).get("response", {}).get("response", {})
    )

    assert response_options.get("neverError") is True
    assert response_options.get("fullResponse") is not True
    assert _successors(workflow, "Typed AI analysis") == ["Analysis completed?"]
    assert _successors(workflow, "Analysis completed?", 1) == ["Record requires_attention"]


def test_non_completed_analysis_records_attention_without_replay_or_success_callbacks() -> None:
    workflow = _workflow("incident-analysis-handoff.v1.json")
    nodes = _nodes_by_name(workflow)
    recovery = nodes["Record requires_attention"]["parameters"]

    assert "/orchestration/recovery" in recovery["url"]
    assert '"expected_state":"intake_received"' in recovery["jsonBody"]
    assert '"run_id":"{{$(' in recovery["jsonBody"]
    assert '"external_execution_id":"{{$execution.id}}"' in recovery["jsonBody"]
    assert '"idempotency_key":"recovery:{{$(' in recovery["jsonBody"]
    assert "model_unavailable" in recovery["jsonBody"]
    assert "policy_failed" in recovery["jsonBody"]
    assert "replay" not in recovery["jsonBody"].lower()


def test_n8n_definitions_use_only_allowlisted_api_and_broker_credentials() -> None:
    handoff = (WORKFLOW_DIR / "incident-analysis-handoff.v1.json").read_text(encoding="utf-8")
    recovery = (WORKFLOW_DIR / "incident-analysis-error-recovery.v1.json").read_text(
        encoding="utf-8"
    )
    combined = f"{handoff}\n{recovery}".lower()

    assert "httpheaderauth" in combined
    assert "kafka" in combined
    assert "postgres" not in combined
    assert "minio" not in combined
    assert "action-gateway" not in combined
    assert "reclaim-orchestrator-service" in combined
    assert "requires_attention" in recovery
