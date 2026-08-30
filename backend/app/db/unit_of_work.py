"""Explicit PostgreSQL transaction boundaries for authoritative writes."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

from app.auth.oidc import TenantAuthorizationContext
from app.db.repositories import (
    ActionExecutionRepository,
    ActionProposalRepository,
    ApprovalRepository,
    AttributionRepository,
    AuditRecordRepository,
    CaseRepository,
    ConnectorConfigurationRepository,
    EscalationRepository,
    EvaluationCaseRepository,
    EvidenceItemRepository,
    FinancialExposureRepository,
    IncidentRepository,
    PolicyDecisionRepository,
    PolicyVersionRepository,
    ReplayRunRepository,
    TenantRepository,
    TimelineEventRepository,
    VerificationRepository,
    WebhookDeliveryRepository,
)
from app.db.tenant_context import TenantContext
from app.events.inbox import InboxMessageRepository
from app.events.outbox import OutboxEventRepository


class PostgresUnitOfWork:
    """Own one PostgreSQL transaction and expose only tenant-scoped repositories.

    The factory is injected so application wiring owns connection pooling and tests
    can use a recording connection.  No repository owns an in-memory business store.
    """

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        self._connection_factory = connection_factory
        self.authorization_context = authorization_context
        self.tenant_context = TenantContext.from_authorization_context(authorization_context)
        self.connection: Any | None = None
        self.tenants: TenantRepository
        self.incidents: IncidentRepository
        self.cases: CaseRepository
        self.audit: AuditRecordRepository
        self.connectors: ConnectorConfigurationRepository
        self.evidence: EvidenceItemRepository
        self.timeline: TimelineEventRepository
        self.attributions: AttributionRepository
        self.exposures: FinancialExposureRepository
        self.policy_versions: PolicyVersionRepository
        self.policy_decisions: PolicyDecisionRepository
        self.proposals: ActionProposalRepository
        self.approvals: ApprovalRepository
        self.actions: ActionExecutionRepository
        self.verifications: VerificationRepository
        self.escalations: EscalationRepository
        self.replay_runs: ReplayRunRepository
        self.evaluation_cases: EvaluationCaseRepository
        self.outbox: OutboxEventRepository
        self.inbox: InboxMessageRepository
        self.webhooks: WebhookDeliveryRepository

    def __enter__(self) -> Self:
        self.connection = self._connection_factory()
        self.connection.execute("BEGIN")
        self.tenant_context.apply(self.connection)
        self.tenants = TenantRepository(self.connection, self.tenant_context)
        self.incidents = IncidentRepository(self.connection, self.tenant_context)
        self.cases = CaseRepository(self.connection, self.tenant_context)
        self.audit = AuditRecordRepository(self.connection, self.tenant_context)
        self.connectors = ConnectorConfigurationRepository(self.connection, self.tenant_context)
        self.evidence = EvidenceItemRepository(self.connection, self.tenant_context)
        self.timeline = TimelineEventRepository(self.connection, self.tenant_context)
        self.attributions = AttributionRepository(self.connection, self.tenant_context)
        self.exposures = FinancialExposureRepository(self.connection, self.tenant_context)
        self.policy_versions = PolicyVersionRepository(self.connection, self.tenant_context)
        self.policy_decisions = PolicyDecisionRepository(self.connection, self.tenant_context)
        self.proposals = ActionProposalRepository(self.connection, self.tenant_context)
        self.approvals = ApprovalRepository(self.connection, self.tenant_context)
        self.actions = ActionExecutionRepository(self.connection, self.tenant_context)
        self.verifications = VerificationRepository(self.connection, self.tenant_context)
        self.escalations = EscalationRepository(self.connection, self.tenant_context)
        self.replay_runs = ReplayRunRepository(self.connection, self.tenant_context)
        self.evaluation_cases = EvaluationCaseRepository(self.connection, self.tenant_context)
        self.outbox = OutboxEventRepository(self.connection, self.tenant_context)
        self.inbox = InboxMessageRepository(self.connection, self.tenant_context)
        self.webhooks = WebhookDeliveryRepository(self.connection, self.tenant_context)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.connection is None:
            return
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
            self.connection = None
