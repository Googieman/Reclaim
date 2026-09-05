"""Assembled FastAPI entry point for the source-built RECLAIM runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.api_compat import validate_fresh_agent_configuration
from app.config import Settings, get_settings
from app.help_chat.http_gateway import HttpHelpGateway
from app.local_runtime import LocalDemoRuntime, create_local_runtime_router
from app.observability.metrics import prometheus_payload, set_postgres_health
from app.runtime import HostedRuntime
from packages.contracts.analysis_policy import ModelBudget
from replay.mode_selection import ModeSelection, select_mode
from replay.runner import ReplayRunner

from .agent_runs import create_agent_router
from .approvals import create_approvals_router
from .case_inbox import create_case_inbox_router
from .demo import create_demo_router
from .help_chat import create_help_chat_router
from .intake import RequestBodySizeLimitMiddleware, create_intake_router
from .operator_view import create_operator_view_router
from .orchestration import create_orchestration_router
from .replay import create_replay_router


def create_app(
    *,
    settings: Settings | None = None,
    runner: ReplayRunner | None = None,
    agent_provider: Any | None = None,
    agent_request_factory: Any | None = None,
    agent_run_persistence: Any | None = None,
    intake_service: Any | None = None,
    case_inbox_service: Any | None = None,
    orchestration_service: Any | None = None,
    oidc_verifier: Any | None = None,
    readiness_check: Callable[[], None] | None = None,
    help_chat_gateway: Any | None = None,
) -> Any:
    """Assemble the safe product surface.

    The unauthenticated demonstration surface exists only under an explicit,
    non-production, replay-only configuration.  Mutable control-plane routes
    are intentionally not mounted in this runtime.
    """

    from fastapi import FastAPI, HTTPException

    configured = settings or get_settings()
    replay_runner = runner or ReplayRunner()
    if configured.demo_read_only_enabled:
        _validate_demo_configuration(configured)
    if configured.fresh_agent_enabled:
        _validate_fresh_agent_configuration(
            configured,
            provider_available=agent_provider is not None or agent_request_factory is not None,
        )
    local_runtime = LocalDemoRuntime(configured) if configured.authoritative_demo_enabled else None
    local_verifier = oidc_verifier
    if local_runtime is not None:
        if local_verifier is None:
            from app.auth.local_demo import LocalDemoVerifier

            local_verifier = LocalDemoVerifier()
    mode = (
        local_runtime.mode_payload()
        if local_runtime is not None
        else _mode_from_settings(configured)
    )

    application = FastAPI(
        title="RECLAIM API",
        version="0.1.0",
        description="Tenant-scoped incident containment runtime",
    )

    if configured.help_chat_enabled:
        if local_verifier is None:
            raise ValueError("enabled help chat requires a verified identity implementation")
        if help_chat_gateway is None:
            configured_gateway = _build_help_gateway(configured)
            application.add_event_handler("shutdown", configured_gateway.close)
        else:
            configured_gateway = help_chat_gateway
        from app.help_chat.retrieval import DocumentationRetriever
        from app.help_chat.service import HelpChatService

        application.include_router(
            create_help_chat_router(
                service=HelpChatService(
                    retriever=DocumentationRetriever.from_default_index(),
                    gateway=configured_gateway,
                    profile=configured.help_chat_profile,
                ),
                oidc_verifier=local_verifier,
            )
        )

    @application.get("/metrics", include_in_schema=False)
    def metrics() -> Any:
        payload, content_type = prometheus_payload()
        from fastapi.responses import Response

        return Response(content=payload, media_type=content_type)

    @application.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "live", "service": "reclaim-api"}

    @application.get("/health/ready")
    def readiness() -> dict[str, Any]:
        try:
            if local_runtime is not None:
                local_runtime.readiness()
            elif readiness_check is not None:
                readiness_check()
            else:
                replay_runner.run(mode="replay")
            set_postgres_health(True)
        except Exception as exc:
            set_postgres_health(False)
            detail = (
                "authoritative PostgreSQL is unavailable"
                if local_runtime is not None
                else "canonical replay is unavailable"
            )
            raise HTTPException(status_code=503, detail=detail) from exc
        return {
            "status": "ready",
            "service": "reclaim-api",
            "mode": mode["final_mode"] if isinstance(mode, dict) else mode.final_mode,
            "demo_read_only": configured.demo_read_only_enabled,
            "live_actions_enabled": mode["live_actions_enabled"]
            if isinstance(mode, dict)
            else mode.live_actions_enabled,
            "live_financial_actions_enabled": mode["live_financial_actions_enabled"]
            if isinstance(mode, dict)
            else mode.live_financial_actions_enabled,
        }

    if configured.demo_read_only_enabled:
        provider = lambda: mode  # noqa: E731 - narrow dependency provider
        application.include_router(create_demo_router(availability_provider=provider))
        application.include_router(create_replay_router(runner=replay_runner))
        application.include_router(create_operator_view_router(runner=replay_runner, mode=mode))
    elif local_runtime is not None:
        provider = lambda: mode  # noqa: E731 - narrow dependency provider
        application.include_router(
            create_demo_router(availability_provider=provider, oidc_verifier=local_verifier)
        )
        application.include_router(create_replay_router(runner=replay_runner))
        application.include_router(
            create_local_runtime_router(runtime=local_runtime, verifier=local_verifier)
        )
        application.include_router(
            create_approvals_router(
                oidc_verifier=local_verifier,
                service=local_runtime.approval_service,
                on_decision=local_runtime.persist_approval_decision,
                request_resolver=local_runtime.restore_approval_request,
            )
        )
        boundary = _build_authoritative_boundary(
            configured,
            local_runtime=local_runtime,
            intake_service=intake_service,
            case_inbox_service=case_inbox_service,
            orchestration_service=orchestration_service,
        )
        application.add_middleware(
            RequestBodySizeLimitMiddleware,
            max_bytes=configured.raw_object_max_bytes,
        )
        application.include_router(
            create_intake_router(
                intake_service=boundary[0],
                oidc_verifier=local_verifier,
            )
        )
        application.include_router(
            create_case_inbox_router(service=boundary[1], oidc_verifier=local_verifier)
        )
        application.include_router(
            create_orchestration_router(service=boundary[2], oidc_verifier=local_verifier)
        )
    elif (
        intake_service is not None
        and case_inbox_service is not None
        and orchestration_service is not None
        and local_verifier is not None
    ):
        application.add_middleware(
            RequestBodySizeLimitMiddleware,
            max_bytes=configured.raw_object_max_bytes,
        )
        application.include_router(
            create_intake_router(intake_service=intake_service, oidc_verifier=local_verifier)
        )
        application.include_router(
            create_case_inbox_router(service=case_inbox_service, oidc_verifier=local_verifier)
        )
        application.include_router(
            create_orchestration_router(
                service=orchestration_service,
                oidc_verifier=local_verifier,
            )
        )
    if configured.fresh_agent_enabled:
        provider_factory = None
        if agent_provider is not None:
            provider_factory = lambda _profile: agent_provider  # noqa: E731
        application.include_router(
            create_agent_router(
                provider_factory=provider_factory,
                request_factory=(
                    local_runtime.request_for_case
                    if local_runtime is not None
                    else agent_request_factory
                ),
                action_environment=configured.fresh_agent_action_environment,
                default_profile=configured.fresh_agent_profile,
                budget_factory=lambda: ModelBudget(
                    max_tokens=configured.agent_max_tokens,
                    max_tool_calls=configured.agent_max_tool_calls,
                    timeout_seconds=configured.agent_timeout_seconds,
                ),
                fallback_profile=configured.fresh_agent_fallback_profile,
                persistence_callback=(
                    local_runtime.persist_agent_run
                    if local_runtime is not None
                    else agent_run_persistence
                ),
                read_callback=local_runtime.read_agent_run if local_runtime is not None else None,
                oidc_verifier=local_verifier,
            )
        )

    return application


def _build_help_gateway(settings: Settings) -> HttpHelpGateway:
    if not settings.help_gateway_base or not settings.help_gateway_base.strip():
        raise ValueError("enabled help chat requires private model gateway configuration")
    if not settings.help_gateway_token or not settings.help_gateway_token.strip():
        raise ValueError("enabled help chat requires private model gateway configuration")
    return HttpHelpGateway(
        base_url=settings.help_gateway_base,
        service_token=settings.help_gateway_token,
    )


def _validate_demo_configuration(settings: Settings) -> None:
    if (
        settings.environment == "production"
        or settings.run_mode != "replay"
        or settings.replay_label != "replay"
        or settings.live_actions_enabled
        or settings.live_financial_actions_enabled
    ):
        raise ValueError(
            "read-only demo requires a non-production REPLAY configuration with live actions off"
        )


def _mode_from_settings(settings: Settings) -> ModeSelection:
    return select_mode(
        settings.run_mode,
        provider_available=False,
        connector_available=False,
        provider_qualified=False,
        connector_qualified=False,
        live_execution_occurred=False,
        live_actions_enabled=settings.live_actions_enabled,
        live_financial_actions_enabled=settings.live_financial_actions_enabled,
    )


def _validate_fresh_agent_configuration(
    settings: Settings, *, provider_available: bool = False
) -> None:
    validate_fresh_agent_configuration(
        environment=settings.environment,
        live_financial_actions_enabled=settings.live_financial_actions_enabled,
        provider_available=provider_available,
    )


def create_hosted_app(
    *,
    runtime: HostedRuntime,
    agent_provider: Any | None = None,
    agent_request_factory: Any | None = None,
    agent_run_persistence: Any | None = None,
    help_chat_gateway: Any | None = None,
) -> Any:
    """Mount the hosted runtime with DB-backed readiness and no demo routes."""

    if runtime.intake_service is None or runtime.case_inbox_service is None:
        raise ValueError("hosted runtime services are incomplete")
    if runtime.orchestration_service is None:
        raise ValueError("hosted orchestration service is incomplete")
    return create_app(
        settings=runtime.settings,
        intake_service=runtime.intake_service,
        case_inbox_service=runtime.case_inbox_service,
        orchestration_service=runtime.orchestration_service,
        oidc_verifier=runtime.oidc_verifier,
        agent_provider=agent_provider,
        agent_request_factory=agent_request_factory,
        agent_run_persistence=agent_run_persistence,
        help_chat_gateway=help_chat_gateway,
        readiness_check=runtime.check_readiness,
    )


def _build_authoritative_boundary(
    settings: Settings,
    *,
    local_runtime: LocalDemoRuntime,
    intake_service: Any | None,
    case_inbox_service: Any | None,
    orchestration_service: Any | None,
) -> tuple[Any, Any, Any]:
    """Build production-shaped services without giving n8n database access."""

    if intake_service is None:
        from app.intake.service import IncidentIntakeService
        from app.storage.minio_evidence import ImmutableEvidenceStore

        intake_service = IncidentIntakeService(
            unit_of_work_factory=local_runtime.unit_of_work_factory,
            raw_report_store=ImmutableEvidenceStore.from_endpoint(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            ),
        )
    if case_inbox_service is None:
        from app.cases.inbox import CaseInboxService

        case_inbox_service = CaseInboxService(
            unit_of_work_factory=local_runtime.unit_of_work_factory
        )
    if orchestration_service is None:
        from app.orchestration.service import OrchestrationService

        orchestration_service = OrchestrationService(
            unit_of_work_factory=local_runtime.unit_of_work_factory,
            workflow_version=settings.n8n_workflow_version,
        )
    return intake_service, case_inbox_service, orchestration_service


app = create_app()


__all__ = ["app", "create_app", "create_hosted_app"]
