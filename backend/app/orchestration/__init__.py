"""n8n-facing, orchestrator-neutral application boundaries."""

from .service import OrchestrationService, OrchestrationServiceError

__all__ = ["OrchestrationService", "OrchestrationServiceError"]
