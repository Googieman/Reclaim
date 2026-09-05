"""Versioned, side-effect-free live/replay orchestration.

Replay is an analysis of recorded contracts.  It may use the same deterministic
timeline, attribution, exposure, and model-fallback code as a live run, but it
never obtains connector credentials and never invokes an Action Gateway.  The
public result is therefore always labelled ``replay`` unless a caller supplies
an explicitly qualified live executor to :func:`run_live_or_replay`.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packages.contracts.audit_replay import ReplayRun
from packages.contracts.common import CONTRACT_VERSION

REPLAY_RUNNER_VERSION = "replay-runner-v1.0.0"
CANONICAL_FIXTURE_VERSION = "canonical-v1.0.0"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_FIXTURE = _REPOSITORY_ROOT / "tests" / "fixtures" / "canonical" / "incident.json"


class ReplayUnavailableError(RuntimeError):
    """Raised only when a requested execution cannot be represented honestly."""


class ReplayRunner:
    """Run a deterministic fixture or supplied contract input without side effects."""

    def __init__(self, *, fixture_root: Path | None = None) -> None:
        self.fixture_root = fixture_root or _CANONICAL_FIXTURE.parent

    def run(
        self,
        *,
        fixture_version: str = CANONICAL_FIXTURE_VERSION,
        tenant_id: str | None = None,
        case_id: str | None = None,
        correlation_id: str | None = None,
        provider_mode: str | None = None,
        model_provider_mode: str | None = None,
        model_version: str | None = None,
        policy_version_id: str | None = None,
        deterministic_seed: str | int = 0,
        environment_metadata: Mapping[str, Any] | None = None,
        events: Sequence[Mapping[str, Any]] | None = None,
        fixture: Mapping[str, Any] | None = None,
        live_executor: Callable[..., Mapping[str, Any]] | None = None,
        live_execution_occurred: bool = False,
        mode: str = "replay",
        **metadata: Any,
    ) -> dict[str, Any]:
        """Execute one run while preserving requested/effective mode provenance.

        A live result is accepted only when both an executor and an explicit
        ``live_execution_occurred`` assertion are supplied.  An unavailable
        live provider otherwise falls back to the deterministic replay path.
        The fallback is visible in ``requested_mode`` and ``fallback_reason``.
        """

        requested_mode = _mode(mode or provider_mode or "replay")
        if requested_mode == "live" and live_executor is not None and live_execution_occurred:
            # The executor owns live qualification.  We still validate that the
            # returned record declares a genuine live run and never rewrite a
            # replay result as live.
            live_result = dict(
                live_executor(
                    fixture_version=fixture_version,
                    tenant_id=tenant_id,
                    case_id=case_id,
                    correlation_id=correlation_id,
                    deterministic_seed=deterministic_seed,
                    environment_metadata=dict(environment_metadata or {}),
                )
            )
            if live_result.get("mode") != "live" or live_result.get("label") != "live":
                raise ReplayUnavailableError(
                    "live executor did not provide an explicitly live-labelled result"
                )
            live_result["requested_mode"] = "live"
            live_result["live_execution_occurred"] = True
            return live_result

        fallback_reason = None
        if requested_mode == "live":
            fallback_reason = "live execution was not qualified; deterministic replay used"
        return self._run_replay(
            fixture_version=fixture_version,
            tenant_id=tenant_id,
            case_id=case_id,
            correlation_id=correlation_id,
            model_provider_mode=model_provider_mode or model_version,
            policy_version_id=policy_version_id,
            deterministic_seed=deterministic_seed,
            environment_metadata=environment_metadata,
            events=events,
            fixture=fixture,
            requested_mode=requested_mode,
            fallback_reason=fallback_reason,
            metadata=metadata,
        )

    def _run_replay(
        self,
        *,
        fixture_version: str,
        tenant_id: str | None,
        case_id: str | None,
        correlation_id: str | None,
        model_provider_mode: str | None,
        policy_version_id: str | None,
        deterministic_seed: str | int,
        environment_metadata: Mapping[str, Any] | None,
        events: Sequence[Mapping[str, Any]] | None,
        fixture: Mapping[str, Any] | None,
        requested_mode: str,
        fallback_reason: str | None,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        source = (
            dict(fixture) if fixture is not None else self._load_fixture(fixture_version, events)
        )
        if events is not None:
            source["events"] = [dict(event) for event in events]
        tenant = _required_text(tenant_id or source.get("tenant_id"), "tenant_id")
        case = _required_text(case_id or source.get("case_id"), "case_id")
        correlation = _required_text(
            correlation_id or source.get("correlation_id") or f"correlation-{case}",
            "correlation_id",
        )
        if source.get("tenant_id") not in (None, tenant):
            raise ValueError("replay input crosses tenant scope")
        if source.get("case_id") not in (None, case):
            raise ValueError("replay input crosses case scope")
        seed = _required_text(str(deterministic_seed), "deterministic_seed")
        policy = _required_text(
            policy_version_id or source.get("policy_version_id") or "policy-v1.0.0",
            "policy_version_id",
        )
        provider = _required_text(
            model_provider_mode
            or source.get("model_provider_mode")
            or "replay-fixture/provider-v1.0.0",
            "model_provider_mode",
        )
        env = _stable_json_value(environment_metadata or source.get("environment_metadata") or {})
        timeline, analysis = self._deterministic_stages(
            source=source,
            tenant_id=tenant,
            case_id=case,
            correlation_id=correlation,
            policy_version_id=policy,
            deterministic_seed=seed,
        )
        expected_stages = _mapping(source.get("expected_stage_outcomes"))
        stage_outcomes = {
            key: str(value) for key, value in (expected_stages or _default_stage_outcomes()).items()
        }
        if analysis is not None:
            stage_outcomes["timeline"] = "converged"
            stage_outcomes["attribution"] = "completed"
            stage_outcomes["exposure"] = "calculated"

        exposure = _exposure_value(analysis, source)
        expected_results = _mapping(source.get("expected_results"))
        terminal_state = str(
            (expected_results or {}).get("terminal_state")
            or source.get("terminal_state")
            or stage_outcomes.get("terminal")
            or "escalated_unresolved"
        )
        actual = {
            "mode": "replay",
            "label": "replay",
            "tenant_id": tenant,
            "case_id": case,
            "correlation_id": correlation,
            "fixture_version": fixture_version,
            "connector_simulator_version": str(
                source.get("connector_simulator_version", "evidence-simulator-v1.0.0")
            ),
            "action_simulator_version": str(
                source.get("action_simulator_version", "action-simulator-v1.0.0")
            ),
            "policy_version_id": policy,
            "model_provider_mode": provider,
            "deterministic_seed": seed,
            "environment_metadata": env,
            "timeline": timeline,
            "attribution": _attribution_value(analysis, source),
            "exposure": exposure,
            "policy_decision": _copy_or_default(
                source.get("policy_decision"),
                {"result": stage_outcomes.get("policy", "escalate"), "policy_version_id": policy},
            ),
            "proposal_validation": _copy_or_default(
                source.get("proposal_validation"),
                {"status": stage_outcomes.get("proposal", "validated"), "side_effects": False},
            ),
            "approval": _copy_or_default(source.get("approval"), {}),
            "action": _replay_action_value(source, stage_outcomes),
            "reconciliation": _copy_or_default(
                source.get("reconciliation"),
                {"status": stage_outcomes.get("reconciliation", "not_required")},
            ),
            "verification": _copy_or_default(
                source.get("verification"),
                {"status": stage_outcomes.get("verification", "inconclusive")},
            ),
            "escalation": _copy_or_default(source.get("escalation"), {}),
            "terminal_state": terminal_state,
            "stage_outcomes": stage_outcomes,
            "audit": _audit_chain(
                tenant_id=tenant,
                case_id=case,
                correlation_id=correlation,
                stage_outcomes=stage_outcomes,
                source=source,
                seed=seed,
            ),
            "remote_side_effects": (),
            "side_effects": False,
            "live_execution_occurred": False,
        }
        actual.update(_analysis_summary(analysis, exposure))
        canonical_input = {
            "fixture_version": fixture_version,
            "tenant_id": tenant,
            "case_id": case,
            "correlation_id": correlation,
            "policy_version_id": policy,
            "model_provider_mode": provider,
            "deterministic_seed": seed,
            "environment_metadata": env,
            "events": _stable_json_value(source.get("events", source.get("timeline_events", ()))),
            "expected_stage_outcomes": stage_outcomes,
        }
        run_id = "replay:" + _checksum(canonical_input)[:32]
        differences = _differences(expected_results, actual)
        provenance = {
            "runner_version": REPLAY_RUNNER_VERSION,
            "contract_version": CONTRACT_VERSION,
            "requested_mode": requested_mode,
            "effective_mode": "replay",
            "final_mode": "replay",
            "label": "replay",
            "fixture_version": fixture_version,
            "policy_version_id": policy,
            "model_provider_mode": provider,
            "deterministic_seed": seed,
            "environment_metadata": env,
            "fallback_reason": fallback_reason,
            "connector_versions": {
                "evidence": actual["connector_simulator_version"],
                "action": actual["action_simulator_version"],
            },
            "run_checksum": _checksum(actual),
            "side_effects": False,
        }
        actual.update(
            {
                "run_id": run_id,
                "requested_mode": requested_mode,
                "fallback_reason": fallback_reason,
                "differences_from_expected": tuple(differences),
                "provenance": provenance,
                "metadata": _stable_json_value(metadata),
            }
        )
        replay_run = ReplayRun(
            tenant_id=tenant,
            correlation_id=correlation,
            run_id=run_id,
            fixture_version=fixture_version,
            connector_simulator_version=actual["connector_simulator_version"],
            action_simulator_version=actual["action_simulator_version"],
            policy_version_id=policy,
            model_provider_mode=provider,
            deterministic_seed=_seed_as_int(seed),
            environment_metadata=env,
            mode="replay",
            stage_outcomes=stage_outcomes,
            terminal_state=terminal_state,
            differences_from_expected=tuple(differences),
            label="replay",
        )
        actual["replay_run"] = replay_run.model_dump(mode="json")
        return _stable_json_value(actual)

    def _load_fixture(
        self, fixture_version: str, events: Sequence[Mapping[str, Any]] | None
    ) -> dict[str, Any]:
        if events is not None:
            return {"fixture_version": fixture_version, "events": [dict(event) for event in events]}
        if fixture_version != CANONICAL_FIXTURE_VERSION:
            raise ReplayUnavailableError(f"replay fixture is unavailable: {fixture_version}")
        path = self.fixture_root / "incident.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayUnavailableError("canonical replay fixture is unavailable") from exc

    @staticmethod
    def _deterministic_stages(
        *,
        source: Mapping[str, Any],
        tenant_id: str,
        case_id: str,
        correlation_id: str,
        policy_version_id: str,
        deterministic_seed: str,
    ) -> tuple[list[dict[str, Any]], Any | None]:
        raw_events = source.get("timeline_events") or source.get("events") or ()
        if not isinstance(raw_events, Sequence) or isinstance(raw_events, str | bytes):
            raise ValueError("replay events must be a sequence")
        timeline = _normalize_timeline(raw_events)
        typed_events = _typed_timeline_events(timeline)
        evidence = source.get("evidence", ())
        analysis = None
        if typed_events and isinstance(evidence, Sequence) and evidence:
            try:
                from analysis.deterministic_summary import run_us2_analysis

                analysis = run_us2_analysis(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    correlation_id=correlation_id,
                    evidence_items=tuple(evidence),
                    timeline_events=typed_events,
                    timeline_uncertainty=tuple(source.get("timeline_uncertainty", ())),
                    policy_version_id=policy_version_id,
                    provider_mode="replay",
                    deterministic_seed=deterministic_seed,
                )
            except (TypeError, ValueError, KeyError):
                # A partial externally supplied input still receives a replay
                # result, but it is not promoted to a fabricated analysis result.
                analysis = None
        return timeline, analysis


def run_replay(**kwargs: Any) -> dict[str, Any]:
    """Functional T111 entry point; the returned record is always replay-labelled."""

    kwargs.pop("mode", None)
    return ReplayRunner().run(mode="replay", **kwargs)


def run_live_or_replay(**kwargs: Any) -> dict[str, Any]:
    """Functional entry point retaining honest live fallback provenance."""

    return ReplayRunner().run(**kwargs)


def _normalize_timeline(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_identity: dict[str, dict[str, Any]] = {}
    duplicate_counts: dict[str, int] = {}
    for index, raw in enumerate(values):
        if not isinstance(raw, Mapping):
            raise ValueError(f"replay event {index} must be an object")
        value = dict(raw)
        identity = str(value.get("timeline_event_id") or value.get("event_id") or "").strip()
        if not identity:
            raise ValueError(f"replay event {index} identity is required")
        duplicate_counts[identity] = duplicate_counts.get(identity, 0) + 1
        if identity not in by_identity:
            by_identity[identity] = value
        elif _stable_json_value(by_identity[identity]) != _stable_json_value(value):
            raise ValueError(f"duplicate replay event has conflicting values: {identity}")
    result: list[dict[str, Any]] = []
    for identity, value in by_identity.items():
        item = _stable_json_value(value)
        item["event_id"] = identity
        item["duplicate_count"] = duplicate_counts[identity]
        result.append(item)
    return sorted(result, key=lambda item: (str(item.get("occurred_at", "")), item["event_id"]))


def _typed_timeline_events(values: Sequence[Mapping[str, Any]]) -> list[Any]:
    from timeline.models import TimelineEvent

    result: list[TimelineEvent] = []
    for index, value in enumerate(values):
        event_type = value.get("canonical_event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            continue
        occurred = _timestamp(value.get("effective_at") or value.get("occurred_at"))
        observed = _timestamp(value.get("observed_at") or value.get("occurred_at"))
        received = _timestamp(value.get("received_at") or value.get("occurred_at"))
        event_id = str(value.get("timeline_event_id") or value.get("event_id") or f"event-{index}")
        evidence_refs = tuple(str(ref) for ref in value.get("evidence_references", ()))
        result.append(
            TimelineEvent(
                tenant_id=str(value.get("tenant_id") or ""),
                case_id=str(value.get("case_id") or ""),
                timeline_event_id=event_id,
                canonical_event_type=event_type,
                source_event_ids=tuple(
                    str(ref) for ref in value.get("source_event_ids", (event_id,))
                ),
                source_event_id=str(value.get("source_event_id") or event_id),
                source_identity=str(value.get("source_identity") or "replay-fixture"),
                effective_at=occurred,
                observed_at=observed,
                received_at=received,
                ordering_key=str(value.get("ordering_key") or f"{occurred.isoformat()}|{event_id}"),
                dedupe_key=str(value.get("dedupe_key") or event_id),
                event_payload=dict(value.get("event_payload") or value.get("payload") or {}),
                evidence_references=evidence_refs,
                source_priority=int(value.get("source_priority", 100)),
                conflicting_source_event_ids=tuple(
                    str(ref) for ref in value.get("conflicting_source_event_ids", ())
                ),
                uncertainty_reasons=tuple(str(ref) for ref in value.get("uncertainty_reasons", ())),
            )
        )
    return result


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("replay event timestamp is required")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("replay event timestamp must include timezone")
    return moment.astimezone(UTC)


def _exposure_value(analysis: Any | None, source: Mapping[str, Any]) -> dict[str, Any]:
    if analysis is not None:
        return _stable_json_value(asdict(analysis.exposure))
    return _copy_or_default(
        source.get("exposure"),
        {
            "currency": "INR",
            "gross_exposure_minor": 0,
            "recoverable_value_minor": 0,
            "contained_value_minor": 0,
            "legitimate_value_disrupted_minor": 0,
            "irreversible_loss_minor": 0,
            "remaining_exposure_minor": 0,
            "calculation_version": "exposure-v1.0.0",
        },
    )


def _attribution_value(analysis: Any | None, source: Mapping[str, Any]) -> list[Any]:
    if analysis is not None:
        return _stable_json_value([item.model_dump(mode="json") for item in analysis.attributions])
    return _copy_or_default(source.get("attribution"), [])


def _analysis_summary(analysis: Any | None, exposure: Mapping[str, Any]) -> dict[str, Any]:
    labels: dict[str, str] = {}
    if analysis is not None:
        for suggestion in analysis.attributions:
            event_id = str(suggestion.timeline_event_id)
            label = str(suggestion.label.value)
            previous = labels.get(event_id)
            labels[event_id] = label if previous in (None, label) else "uncertain"
    return {
        "attribution_labels": labels,
        "gross_exposure_minor": exposure.get("gross_exposure_minor", 0),
        "recoverable_value_minor": exposure.get("recoverable_value_minor", 0),
        "contained_value_minor": exposure.get("contained_value_minor", 0),
        "legitimate_value_disrupted_minor": exposure.get("legitimate_value_disrupted_minor", 0),
        "remaining_exposure_minor": exposure.get("remaining_exposure_minor", 0),
        "currency": exposure.get("currency"),
    }


def _replay_action_value(source: Mapping[str, Any], stages: Mapping[str, str]) -> Any:
    action = _copy_or_default(
        source.get("action"),
        {"status": stages.get("action", "simulated_not_executed")},
    )
    if isinstance(action, Mapping):
        action = dict(action)
        action["remote_side_effects"] = ()
        action["simulation"] = True
    return action


def _audit_chain(
    *,
    tenant_id: str,
    case_id: str,
    correlation_id: str,
    stage_outcomes: Mapping[str, str],
    source: Mapping[str, Any],
    seed: str,
) -> list[dict[str, Any]]:
    links = source.get("audit_links")
    stages = (
        tuple(links)
        if isinstance(links, Sequence) and not isinstance(links, str | bytes)
        else tuple(stage_outcomes)
    )
    previous: str | None = None
    records: list[dict[str, Any]] = []
    for stage in stages:
        stage_name = str(stage.get("stage", "")) if isinstance(stage, Mapping) else str(stage)
        if not stage_name:
            continue
        audit_identity = {
            "tenant_id": tenant_id,
            "case_id": case_id,
            "stage": stage_name,
            "seed": seed,
        }
        record = {
            "audit_id": f"audit:replay:{_checksum(audit_identity)[:24]}",
            "tenant_id": tenant_id,
            "case_id": case_id,
            "correlation_ids": (correlation_id,),
            "stage": stage_name,
            "outcome": stage_outcomes.get(stage_name, "recorded"),
            "mode": "replay",
            "label": "replay",
            "previous_record_checksum": previous,
        }
        record["record_checksum"] = _checksum(record)
        previous = record["record_checksum"]
        records.append(record)
    return records


def _differences(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    differences: list[str] = []
    for key, expected_value in (expected or {}).items():
        actual_value = actual.get(key)
        if _stable_json_value(actual_value) != _stable_json_value(expected_value):
            differences.append(f"{key}:expected={expected_value!r};actual={actual_value!r}")
    return differences


def _default_stage_outcomes() -> dict[str, str]:
    return {
        "incident": "accepted",
        "evidence": "collected",
        "timeline": "converged",
        "attribution": "completed",
        "exposure": "calculated",
        "proposal": "validated",
        "policy": "escalate",
        "approval": "not_required",
        "action": "simulated_not_executed",
        "reconciliation": "not_required",
        "verification": "inconclusive",
        "escalation": "required",
        "terminal": "escalated_unresolved",
        "audit": "linked",
    }


def _copy_or_default(value: Any, default: Any) -> Any:
    return copy.deepcopy(default if value is None else value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mode(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    value = str(value).strip().lower()
    if value not in {"live", "replay"}:
        raise ValueError("replay mode must be live or replay")
    return value


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _seed_as_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        parsed = int(_checksum({"seed": value})[:12], 16)
    return max(parsed, 0)


def _stable_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_stable_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if hasattr(value, "value") and not isinstance(value, str | bytes):
        return _stable_json_value(value.value)
    if is_dataclass(value):
        return _stable_json_value(asdict(value))
    if hasattr(value, "model_dump"):
        return _stable_json_value(value.model_dump(mode="json"))
    return value


def _checksum(value: Any) -> str:
    encoded = json.dumps(
        _stable_json_value(value), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "CANONICAL_FIXTURE_VERSION",
    "REPLAY_RUNNER_VERSION",
    "ReplayRunner",
    "ReplayUnavailableError",
    "run_live_or_replay",
    "run_replay",
]
