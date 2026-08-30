"""Fixture-backed evidence simulators implementing the live connector contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.storage.minio_evidence import checksum_for_bytes
from packages.contracts.connectors import (
    ConnectorFailureState,
    ConnectorLimits,
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
    EvidenceRequest,
    EvidenceResponse,
)

from connectors.evidence.base import EvidenceReadResult, ReadOnlyEvidenceAdapter


class EvidenceSimulatorScenario(StrEnum):
    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class DeterministicEvidenceSimulator(ReadOnlyEvidenceAdapter):
    """Return deterministic, explicitly replay-labeled evidence for one resource."""

    def __init__(
        self,
        manifest: ConnectorManifest,
        *,
        scenario: EvidenceSimulatorScenario | str = EvidenceSimulatorScenario.VALID,
        fixture_directory: str | Path | None = None,
        fixtures: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        if manifest.mode is not ConnectorMode.SIMULATOR:
            raise ValueError("evidence simulator requires a simulator manifest")
        if len(manifest.resources) != 1:
            raise ValueError("one deterministic simulator must declare one resource")
        try:
            self.scenario = EvidenceSimulatorScenario(scenario)
        except ValueError as exc:
            raise ValueError("unsupported evidence simulator scenario") from exc
        self.fixture_directory = Path(fixture_directory) if fixture_directory else None
        self.fixtures = {key: dict(value) for key, value in (fixtures or {}).items()}
        super().__init__(manifest, reader=self._read_fixture)

    @classmethod
    def for_resource(
        cls,
        tenant_id: str,
        resource_type: str,
        *,
        scenario: EvidenceSimulatorScenario | str = EvidenceSimulatorScenario.VALID,
        fixture_directory: str | Path | None = None,
    ) -> DeterministicEvidenceSimulator:
        manifest = simulator_manifest(tenant_id, resource_type)
        return cls(
            manifest,
            scenario=scenario,
            fixture_directory=fixture_directory,
        )

    def _read_fixture(self, request: EvidenceRequest) -> EvidenceReadResult:
        fixture = self._fixture()
        rendered = self._render_fixture(request, fixture)
        raw_payload = json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode("utf-8")
        checksum = checksum_for_bytes(raw_payload)
        observed_at = _parse_fixture_timestamp(rendered.get("observed_at"), "observed_at")
        collected_at = _parse_fixture_timestamp(rendered.get("collected_at"), "collected_at")
        failure_state = _failure_state(self.scenario)
        normalized_facts = rendered.get("normalized_facts", [])
        if failure_state in {
            ConnectorFailureState.UNAVAILABLE,
            ConnectorFailureState.TIMEOUT,
            ConnectorFailureState.INVALID,
        }:
            normalized_facts = []
        completeness = (
            "partial"
            if self.scenario
            in {
                EvidenceSimulatorScenario.PARTIAL,
                EvidenceSimulatorScenario.TIMEOUT,
                EvidenceSimulatorScenario.UNAVAILABLE,
                EvidenceSimulatorScenario.INVALID,
            }
            else "complete"
        )
        connector_status = (
            "complete" if self.scenario is EvidenceSimulatorScenario.VALID else self.scenario.value
        )
        response = EvidenceResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            case_id=request.case_id,
            connector_id=request.connector_id,
            source_identity=str(rendered["source_identity"]),
            resource_type=request.resource_type,
            observed_at=observed_at,
            collected_at=collected_at,
            completeness=completeness,
            raw_checksum=checksum,
            normalized_facts=list(normalized_facts),
            connector_status=connector_status,
            failure_state=failure_state,
        )
        return EvidenceReadResult(
            response=response,
            raw_payload=raw_payload,
            provenance={
                "mode": "replay",
                "source": str(rendered["provenance"]["source"]),
                "version": str(rendered["provenance"]["version"]),
                "seed": str(rendered["seed"]),
            },
        )

    def _fixture(self) -> dict[str, Any]:
        resource_type = self.manifest.resources[0]
        key = f"{resource_type}:{self.scenario.value}"
        if key in self.fixtures:
            return dict(self.fixtures[key])
        if self.fixture_directory is not None:
            candidates = (
                self.fixture_directory / f"{resource_type}-{self.scenario.value}.json",
                self.fixture_directory / f"{resource_type}.json",
                self.fixture_directory / "session-observation.json"
                if resource_type == "sessions"
                else self.fixture_directory / "missing.json",
            )
            for path in candidates:
                if path.exists():
                    return _load_fixture(path)
        return _default_fixture(resource_type)

    def _render_fixture(
        self,
        request: EvidenceRequest,
        fixture: Mapping[str, Any],
    ) -> dict[str, Any]:
        if fixture.get("mode") != "replay":
            raise ValueError("evidence simulator fixtures must be labeled replay")
        rendered = dict(fixture)
        rendered["tenant_id"] = request.tenant_id
        rendered["case_id"] = request.case_id
        rendered["correlation_id"] = request.correlation_id
        rendered["resource_type"] = request.resource_type
        rendered.setdefault("source_identity", f"merchant-{request.resource_type}-store")
        rendered.setdefault("observed_at", request.requested_at.isoformat())
        rendered.setdefault("collected_at", request.requested_at.isoformat())
        rendered.setdefault("seed", f"reclaim-{request.resource_type}-default")
        rendered.setdefault("provenance", {"source": "development-fixture", "version": "1.0.0"})
        facts = [dict(fact) for fact in rendered.get("normalized_facts", [])]
        if self.scenario is EvidenceSimulatorScenario.DUPLICATE and facts:
            facts.insert(0, dict(facts[0]))
        if self.scenario is EvidenceSimulatorScenario.OUT_OF_ORDER:
            facts.reverse()
        rendered["normalized_facts"] = facts
        rendered["scenario"] = self.scenario.value
        return rendered


def simulator_manifest(tenant_id: str, resource_type: str) -> ConnectorManifest:
    """Build one versioned manifest for an approved simulator resource."""

    return ConnectorManifest(
        tenant_id=tenant_id,
        correlation_id=f"simulator-manifest-{resource_type}",
        connector_id=f"sim-{resource_type}",
        contract_version="1.0.0",
        connector_type=ConnectorType.EVIDENCE,
        mode=ConnectorMode.SIMULATOR,
        resources=(resource_type,),
        operations=("read",),
        auth_scope=(f"merchant:{resource_type}:read",),
        limits=ConnectorLimits(),
        request_schema="evidence.request.v1",
        response_schema="evidence.response.v1",
        timestamp_semantics="event_at then observed_at then collected_at; all UTC",
        idempotency_behavior="duplicate reads are replay-safe",
        failure_states=tuple(ConnectorFailureState),
    )


def build_default_evidence_simulators(
    tenant_id: str = "tenant-a",
    *,
    fixture_directory: str | Path | None = None,
    scenarios: Mapping[str, EvidenceSimulatorScenario | str] | None = None,
) -> dict[str, DeterministicEvidenceSimulator]:
    """Build the six approved resource simulators with stable manifests."""

    scenarios = scenarios or {}
    return {
        f"sim-{resource}": DeterministicEvidenceSimulator.for_resource(
            tenant_id,
            resource,
            scenario=scenarios.get(resource, EvidenceSimulatorScenario.VALID),
            fixture_directory=fixture_directory,
        )
        for resource in (
            "sessions",
            "devices",
            "profile_changes",
            "orders",
            "fulfillment",
            "payments",
        )
    }


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("evidence simulator fixture could not be loaded") from exc
    if not isinstance(value, dict):
        raise ValueError("evidence simulator fixture must be an object")
    if "secret" in value or "credentials" in value:
        raise ValueError("evidence simulator fixture contains forbidden secret material")
    return value


def _parse_fixture_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"evidence fixture {name} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"evidence fixture {name} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"evidence fixture {name} requires explicit timezone")
    return parsed.astimezone(UTC)


def _failure_state(scenario: EvidenceSimulatorScenario) -> ConnectorFailureState | None:
    return {
        EvidenceSimulatorScenario.PARTIAL: ConnectorFailureState.PARTIAL,
        EvidenceSimulatorScenario.STALE: ConnectorFailureState.STALE,
        EvidenceSimulatorScenario.TIMEOUT: ConnectorFailureState.TIMEOUT,
        EvidenceSimulatorScenario.UNAVAILABLE: ConnectorFailureState.UNAVAILABLE,
        EvidenceSimulatorScenario.INVALID: ConnectorFailureState.INVALID,
    }.get(scenario)


def _default_fixture(resource_type: str) -> dict[str, Any]:
    timestamp_by_resource = {
        "sessions": "2026-08-30T09:00:00Z",
        "devices": "2026-08-30T09:05:00Z",
        "profile_changes": "2026-08-30T09:10:00Z",
        "orders": "2026-08-30T09:20:00Z",
        "fulfillment": "2026-08-30T09:30:00Z",
        "payments": "2026-08-30T09:40:00Z",
    }
    event_types = {
        "sessions": "session.opened",
        "devices": "device.registered",
        "profile_changes": "profile.changed",
        "orders": "order.created",
        "fulfillment": "fulfillment.updated",
        "payments": "payment.captured",
    }
    source_event_id = f"{resource_type.replace('_', '-')}-event-1"
    entity_name = resource_type.rstrip("s").replace("_", "-")
    return {
        "schema_version": "1.0.0",
        "fixture_id": f"evidence-{resource_type}-default-001",
        "seed": f"us1-evidence-development-{resource_type}",
        "mode": "replay",
        "provenance": {"source": "development-fixture", "version": "2026-08-30"},
        "source_identity": f"merchant-{resource_type}-store",
        "observed_at": timestamp_by_resource[resource_type],
        "collected_at": "2026-08-30T10:01:00Z",
        "normalized_facts": [
            {
                "source_event_id": source_event_id,
                "canonical_event_type": event_types[resource_type],
                "dedupe_key": f"{entity_name}:{resource_type}-1",
                "event_at": timestamp_by_resource[resource_type],
                "source_priority": 100,
                f"{entity_name}_id": f"{resource_type}-1",
                "state": "observed",
            }
        ],
    }


__all__ = [
    "DeterministicEvidenceSimulator",
    "EvidenceSimulatorScenario",
    "build_default_evidence_simulators",
    "simulator_manifest",
]
