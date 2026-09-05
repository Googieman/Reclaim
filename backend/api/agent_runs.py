"""Tenant-scoped fresh-agent analysis API.

The route is deliberately separate from replay and from every action command. The
default app does not mount it unless explicitly enabled by configuration.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.fresh_run import AgentRun, AgentRunStatus
from agent.model_profiles import (
    ModelProfileError,
    ModelProfileUnavailable,
    build_provider,
    profile_budget,
    resolve_profile,
)
from agent.providers import ModelProvider
from fastapi import APIRouter, Header, HTTPException, Response, status
from packages.contracts.analysis_policy import ModelAnalysisRequest, ModelBudget, ProviderMode
from pydantic import BaseModel, ConfigDict, Field
from replay.runner import _normalize_timeline, _typed_timeline_events

ProviderFactory = Callable[[str], ModelProvider]
RequestFactory = Callable[[str, str, ModelBudget], ModelAnalysisRequest]
PersistenceCallback = Callable[[AgentRun], object]
ReadCallback = Callable[[str, str, str], Mapping[str, Any] | None]


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_profile: str | None = Field(default=None, min_length=1, max_length=100)
    fallback_policy: str = Field(
        default="explicit_unavailable", pattern="^(explicit_unavailable|configured_profile)$"
    )
    budget: ModelBudget | None = None


class AgentRunStore:
    """Small read cache for the no-Postgres local demo.

    Production wiring should supply a PostgreSQL-backed persistence callback. This
    cache is never used for case, policy, approval, action, or terminal authority.
    """

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], AgentRun] = {}

    def save(self, run: AgentRun) -> AgentRun:
        key = (run.request.tenant_id, run.run_id)
        existing = self._runs.get(key)
        if existing is not None and existing.to_dict() != run.to_dict():
            raise ValueError("agent run identity conflicts with an existing run")
        self._runs[key] = run
        return run

    def get(self, *, tenant_id: str, case_id: str, run_id: str) -> AgentRun | None:
        run = self._runs.get((tenant_id, run_id))
        if run is None or run.request.case_id != case_id:
            return None
        return run


def create_agent_router(
    *,
    provider_factory: ProviderFactory | None = None,
    request_factory: RequestFactory | None = None,
    store: AgentRunStore | None = None,
    oidc_verifier: Any | None = None,
    action_environment: str = "simulator",
    default_profile: str = "reclaim-specialist",
    budget_factory: Callable[[], ModelBudget] | None = None,
    fallback_profile: str | None = None,
    persistence_callback: PersistenceCallback | None = None,
    read_callback: ReadCallback | None = None,
) -> Any:
    router = APIRouter()
    run_store = store or AgentRunStore()
    make_provider = provider_factory or _configured_provider
    make_request = request_factory or canonical_live_request

    @router.post("/tenants/{tenant_id}/cases/{case_id}/agent-runs")
    def start_agent_run(
        tenant_id: str,
        case_id: str,
        body: AgentRunRequest,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if oidc_verifier is not None:
            _authorize(oidc_verifier, authorization, tenant_id)
        try:
            profile_name = body.provider_profile or default_profile
            budget = body.budget or (
                budget_factory() if budget_factory is not None else profile_budget()
            )
            request = make_request(tenant_id, case_id, budget)
            provider = make_provider(profile_name)
            fallback = None
            selected_fallback_profile = None
            if body.fallback_policy == "configured_profile":
                selected_fallback_profile = fallback_profile or _configured_fallback_name()
                if selected_fallback_profile:
                    fallback = make_provider(selected_fallback_profile)
            from agent.fresh_run import FreshAgentCoordinator

            run = FreshAgentCoordinator(
                provider,
                profile=profile_name,
                fallback_provider=fallback,
                fallback_profile=selected_fallback_profile,
                action_environment=action_environment,
            ).run(request, deterministic_uncertainty=_context_uncertainty(request))
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="case is not available in this tenant scope"
            ) from exc
        except ModelProfileUnavailable as exc:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            run = _unavailable_run(
                request
                if "request" in locals()
                else _request_for_failure(tenant_id, case_id, body.budget),
                body.provider_profile or default_profile,
                str(exc),
                action_environment,
            )
        except ModelProfileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if persistence_callback is not None:
            # The callback is the production transaction boundary. It receives
            # only the typed, redacted AgentRun; it never receives raw provider
            # output or an execution handle.
            persisted = persistence_callback(run)
        else:
            persisted = None
        saved = run_store.save(run)
        if saved.status is AgentRunStatus.UNAVAILABLE:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        payload = saved.to_dict()
        if isinstance(persisted, Mapping):
            payload.update(dict(persisted))
        return payload

    @router.get("/tenants/{tenant_id}/cases/{case_id}/agent-runs/{run_id}")
    def read_agent_run(
        tenant_id: str,
        case_id: str,
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if oidc_verifier is not None:
            _authorize(oidc_verifier, authorization, tenant_id)
        if read_callback is not None:
            persisted = read_callback(tenant_id, case_id, run_id)
            if persisted is not None:
                return dict(persisted)
        run = run_store.get(tenant_id=tenant_id, case_id=case_id, run_id=run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="fresh agent run was not found")
        return run.to_dict()

    return router


def canonical_live_request(
    tenant_id: str, case_id: str, budget: ModelBudget
) -> ModelAnalysisRequest:
    fixture_path = (
        Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "canonical" / "incident.json"
    )
    source = json.loads(fixture_path.read_text(encoding="utf-8"))
    if source.get("tenant_id") != tenant_id or source.get("case_id") != case_id:
        raise LookupError("canonical fixture does not belong to requested tenant/case")
    timeline = _normalize_timeline(source.get("timeline_events", []))
    typed_events = _typed_timeline_events(timeline)
    if not typed_events:
        raise LookupError("canonical case has no timeline")
    from analysis.deterministic_summary import run_us2_analysis

    deterministic = run_us2_analysis(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=str(source["correlation_id"]),
        evidence_items=tuple(source.get("evidence", [])),
        timeline_events=typed_events,
        timeline_uncertainty=tuple(source.get("timeline_uncertainty", [])),
        policy_version_id=str(source.get("policy_version_id", "policy-v1.0.0")),
        provider_mode=ProviderMode.REPLAY,
        deterministic_seed=str(source.get("deterministic_seed", "0")),
    )
    if deterministic.analysis_request is None:
        raise LookupError("deterministic analysis did not produce a model request")
    context = deterministic.analysis_request.model_copy(deep=True)
    representation = dict(context.redacted_case_representation)
    provenance = dict(representation.get("provenance", {}))
    provenance["mode"] = ProviderMode.LIVE.value
    representation["provenance"] = provenance
    return context.model_copy(
        update={
            "redacted_case_representation": representation,
            "budget": budget,
            "provider_mode": ProviderMode.LIVE,
            "replay_label": ProviderMode.LIVE,
        }
    )


def _configured_provider(profile: str) -> ModelProvider:
    return build_provider(resolve_profile(profile))


def _configured_fallback_name() -> str | None:
    import os

    value = os.getenv("RECLAIM_AGENT_FALLBACK_PROFILE", "").strip()
    return value or None


def _context_uncertainty(request: ModelAnalysisRequest) -> tuple[str, ...]:
    value = request.redacted_case_representation.get("uncertainty", ())
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _request_for_failure(
    tenant_id: str, case_id: str, budget: ModelBudget | None
) -> ModelAnalysisRequest:
    return canonical_live_request(tenant_id, case_id, budget or profile_budget())


def _unavailable_run(
    request: ModelAnalysisRequest, profile: str, error: str, action_environment: str
) -> AgentRun:
    from agent.fresh_run import _checksum  # noqa: PLC0415

    return AgentRun(
        run_id="agent-run:unavailable:" + uuid4().hex,
        request=request,
        status=AgentRunStatus.UNAVAILABLE,
        action_environment=action_environment,
        profile=profile,
        error=" ".join(error.split())[:240],
        request_checksum=_checksum(request.model_dump(mode="json")),
    )


def _authorize(oidc_verifier: Any, authorization: str | None, tenant_id: str) -> Any:
    from app.auth.oidc import IdentityType, RequiredRole
    from fastapi import HTTPException

    if authorization is None:
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(status_code=401, detail="bearer authentication is required")
    try:
        context = oidc_verifier.authorize(token.strip(), tenant_id=tenant_id)
        if context.identity_type is IdentityType.SERVICE:
            context.require_role(RequiredRole.ORCHESTRATOR)
        else:
            context.require_role(RequiredRole.REVIEWER)
        return context
    except Exception as exc:
        raise HTTPException(status_code=403, detail="fresh agent access is not authorized") from exc


__all__ = ["AgentRunRequest", "AgentRunStore", "canonical_live_request", "create_agent_router"]
