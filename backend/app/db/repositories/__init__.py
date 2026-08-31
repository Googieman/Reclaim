"""Explicit tenant-scoped PostgreSQL repositories."""

from .actions import ActionExecutionRepository, VerificationRepository
from .approvals import ApprovalRepository
from .attribution import AttributionRepository
from .audit import AuditRecordRepository
from .base import RepositoryError, TenantScopedRepository
from .cases import CaseRepository
from .connectors import ConnectorConfigurationRepository
from .escalations import EscalationRepository
from .evidence import EvidenceItemRepository
from .finance import FinancialExposureRepository
from .incidents import IncidentCreateResult, IncidentRepository
from .policy import PolicyDecisionRepository, PolicyVersionRepository
from .proposals import ActionProposalRepository
from .provider_correlations import (
    ProviderCorrelationMapping,
    ProviderCorrelationMappingConflictError,
    ProviderCorrelationRepository,
    ProviderCorrelationResolution,
)
from .replay import EvaluationCaseRepository, ReplayRunRepository
from .tenants import TenantRepository
from .timeline import TimelineEventRepository
from .webhooks import (
    WebhookDeliveryCreateResult,
    WebhookDeliveryRepository,
    WebhookQuarantine,
)

__all__ = [
    "AuditRecordRepository",
    "ActionExecutionRepository",
    "ActionProposalRepository",
    "ApprovalRepository",
    "AttributionRepository",
    "CaseRepository",
    "ConnectorConfigurationRepository",
    "EscalationRepository",
    "EvaluationCaseRepository",
    "EvidenceItemRepository",
    "FinancialExposureRepository",
    "IncidentRepository",
    "IncidentCreateResult",
    "PolicyDecisionRepository",
    "PolicyVersionRepository",
    "ProviderCorrelationMapping",
    "ProviderCorrelationMappingConflictError",
    "ProviderCorrelationRepository",
    "ProviderCorrelationResolution",
    "RepositoryError",
    "ReplayRunRepository",
    "TenantRepository",
    "TenantScopedRepository",
    "TimelineEventRepository",
    "VerificationRepository",
    "WebhookDeliveryCreateResult",
    "WebhookDeliveryRepository",
    "WebhookQuarantine",
]
