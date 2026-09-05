"""Authoritative persistence for the n8n handoff state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from packages.contracts.case_inbox import OrchestrationStage, OrchestrationStatus
from packages.contracts.orchestration import OrchestrationOutcome

from .base import RepositoryError, TenantScopedRepository


@dataclass(frozen=True, slots=True)
class OrchestrationRunRecord:
    tenant_id: str
    run_id: str
    case_id: str
    workflow_version: str
    external_execution_id: str
    stage: OrchestrationStage
    status: OrchestrationStatus
    idempotency_key: str
    failure_code: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class OrchestrationRepository(TenantScopedRepository):
    """Persist one idempotent run and its independently idempotent stages."""

    _STAGE_ORDER = {
        OrchestrationStage.NORMALIZE_INTAKE: 0,
        OrchestrationStage.ANALYZE: 1,
        OrchestrationStage.HUMAN_HANDOFF: 2,
    }

    def create_or_get(
        self,
        *,
        run_id: str,
        case_id: str,
        workflow_version: str,
        external_execution_id: str,
        idempotency_key: str,
        queued_at: datetime | None = None,
    ) -> OrchestrationRunRecord:
        for name, value in (
            ("run_id", run_id),
            ("case_id", case_id),
            ("workflow_version", workflow_version),
            ("external_execution_id", external_execution_id),
            ("idempotency_key", idempotency_key),
        ):
            if not value.strip():
                raise RepositoryError(f"{name} is required")
        row = self.fetch_one(
            """
            INSERT INTO public.orchestration_runs (
                tenant_id, run_id, case_id, workflow_version,
                external_execution_id, stage, status, idempotency_key, queued_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, 'normalize_intake', 'queued', %s,
                    COALESCE(%s, now()), COALESCE(%s, now()))
            ON CONFLICT (tenant_id, case_id, idempotency_key) DO NOTHING
            RETURNING tenant_id, run_id, case_id, workflow_version,
                      external_execution_id, stage, status, idempotency_key,
                      failure_code, queued_at, started_at, completed_at, updated_at
            """,
            (
                self.tenant_context.tenant_id,
                run_id,
                case_id,
                workflow_version,
                external_execution_id,
                idempotency_key,
                queued_at,
                queued_at,
            ),
        )
        if row is None:
            row = self.fetch_one(
                """
                SELECT tenant_id, run_id, case_id, workflow_version,
                       external_execution_id, stage, status, idempotency_key,
                       failure_code, queued_at, started_at, completed_at, updated_at
                FROM public.orchestration_runs
                WHERE tenant_id = %s AND case_id = %s AND idempotency_key = %s
                """,
                (self.tenant_context.tenant_id, case_id, idempotency_key),
            )
            if row is None:
                raise RepositoryError("orchestration run disappeared after identity conflict")
            if str(row[2]) != case_id:
                raise RepositoryError("orchestration idempotency key conflicts with another case")
            # The first n8n execution that wins the idempotency key remains the
            # authoritative owner. A duplicate delivery must receive that
            # record so the workflow can stop before invoking later stages.
        return self._record(row)

    def get(self, *, run_id: str) -> OrchestrationRunRecord | None:
        if not run_id.strip():
            raise RepositoryError("run_id is required")
        row = self.fetch_one(
            """
            SELECT tenant_id, run_id, case_id, workflow_version,
                   external_execution_id, stage, status, idempotency_key,
                   failure_code, queued_at, started_at, completed_at, updated_at
            FROM public.orchestration_runs
            WHERE tenant_id = %s AND run_id = %s
            """,
            (self.tenant_context.tenant_id, run_id),
        )
        return None if row is None else self._record(row)

    def latest_for_case(self, *, case_id: str) -> OrchestrationRunRecord | None:
        row = self.fetch_one(
            """
            SELECT tenant_id, run_id, case_id, workflow_version,
                   external_execution_id, stage, status, idempotency_key,
                   failure_code, queued_at, started_at, completed_at, updated_at
            FROM public.orchestration_runs
            WHERE tenant_id = %s AND case_id = %s
            ORDER BY updated_at DESC, run_id DESC
            LIMIT 1
            """,
            (self.tenant_context.tenant_id, case_id),
        )
        return None if row is None else self._record(row)

    def claim(self, *, run_id: str, external_execution_id: str) -> OrchestrationRunRecord:
        """Claim a queued run; repeated n8n deliveries are safe no-ops."""

        row = self.fetch_one(
            """
            UPDATE public.orchestration_runs
            SET status = 'running', started_at = COALESCE(started_at, now()), updated_at = now()
            WHERE tenant_id = %s AND run_id = %s AND external_execution_id = %s
              AND status IN ('queued', 'running')
            RETURNING tenant_id, run_id, case_id, workflow_version,
                      external_execution_id, stage, status, idempotency_key,
                      failure_code, queued_at, started_at, completed_at, updated_at
            """,
            (self.tenant_context.tenant_id, run_id, external_execution_id),
        )
        if row is None:
            record = self.get(run_id=run_id)
            if record is None:
                raise RepositoryError("orchestration run is not present for this tenant")
            if record.external_execution_id != external_execution_id:
                # A duplicate Redpanda delivery may create a second n8n execution
                # before or after the first execution claims the run. Return the
                # authoritative owner so the workflow can compare identities and
                # stop before invoking model or stage side effects a second time.
                return record
            return record
        return self._record(row)

    def advance_stage(
        self,
        *,
        run_id: str,
        stage: OrchestrationStage,
        expected_state: str,
        idempotency_key: str,
        outcome: OrchestrationOutcome,
        failure_code: str | None = None,
    ) -> OrchestrationRunRecord:
        """Apply one allowlisted stage exactly once after case-state validation."""

        if not expected_state.strip() or not idempotency_key.strip():
            raise RepositoryError("expected_state and idempotency_key are required")
        if outcome in {
            OrchestrationOutcome.FAILED,
            OrchestrationOutcome.REQUIRES_ATTENTION,
        } and not (failure_code and failure_code.strip()):
            raise RepositoryError("failure_code is required for a failed orchestration outcome")
        current = self.get(run_id=run_id)
        if current is None:
            raise RepositoryError("orchestration run is not present for this tenant")
        case = self.fetch_one(
            """
            SELECT current_state
            FROM public.cases
            WHERE tenant_id = %s AND case_id = %s
            """,
            (self.tenant_context.tenant_id, current.case_id),
        )
        if case is None:
            raise RepositoryError("orchestration case is not present for this tenant")
        if str(case[0]) != expected_state:
            raise RepositoryError("case state does not match orchestration expected_state")

        attempt_id = f"{run_id}:{stage.value}:{idempotency_key}"
        inserted = self.fetch_one(
            """
            INSERT INTO public.orchestration_stage_attempts (
                tenant_id, attempt_id, run_id, stage, idempotency_key,
                expected_state, outcome, failure_code
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, run_id, stage, idempotency_key) DO NOTHING
            RETURNING attempt_id
            """,
            (
                self.tenant_context.tenant_id,
                attempt_id,
                run_id,
                stage.value,
                idempotency_key,
                expected_state,
                outcome.value,
                failure_code,
            ),
        )
        if inserted is None:
            prior_attempt = self.fetch_one(
                """
                SELECT expected_state, outcome, failure_code
                FROM public.orchestration_stage_attempts
                WHERE tenant_id = %s AND run_id = %s AND stage = %s
                  AND idempotency_key = %s
                """,
                (
                    self.tenant_context.tenant_id,
                    run_id,
                    stage.value,
                    idempotency_key,
                ),
            )
            if prior_attempt is None:
                raise RepositoryError(
                    "orchestration stage attempt disappeared after identity conflict"
                )
            if (
                str(prior_attempt[0]) != expected_state
                or str(prior_attempt[1]) != outcome.value
                or prior_attempt[2] != failure_code
            ):
                raise RepositoryError(
                    "orchestration stage idempotency key conflicts with prior outcome"
                )
            return current
        if self._STAGE_ORDER[stage] < self._STAGE_ORDER[current.stage]:
            raise RepositoryError("orchestration stage cannot move backwards")

        status = _status_for_outcome(stage, outcome)
        completed_at = None if status in {OrchestrationStatus.RUNNING} else datetime.now(UTC)
        row = self.fetch_one(
            """
            UPDATE public.orchestration_runs
            SET stage = %s, status = %s, failure_code = %s,
                completed_at = %s, updated_at = now()
            WHERE tenant_id = %s AND run_id = %s
            RETURNING tenant_id, run_id, case_id, workflow_version,
                      external_execution_id, stage, status, idempotency_key,
                      failure_code, queued_at, started_at, completed_at, updated_at
            """,
            (
                stage.value,
                status.value,
                failure_code,
                completed_at,
                self.tenant_context.tenant_id,
                run_id,
            ),
        )
        if row is None:
            raise RepositoryError("orchestration run disappeared during stage transition")
        return self._record(row)

    def _record(self, row: Any) -> OrchestrationRunRecord:
        try:
            stage = OrchestrationStage(str(row[5]))
            status = OrchestrationStatus(str(row[6]))
        except (IndexError, ValueError) as exc:
            raise RepositoryError("stored orchestration state is invalid") from exc
        return OrchestrationRunRecord(
            tenant_id=str(row[0]),
            run_id=str(row[1]),
            case_id=str(row[2]),
            workflow_version=str(row[3]),
            external_execution_id=str(row[4]),
            stage=stage,
            status=status,
            idempotency_key=str(row[7]),
            failure_code=None if row[8] is None else str(row[8]),
            queued_at=row[9],
            started_at=row[10],
            completed_at=row[11],
            updated_at=row[12],
        )


def _status_for_outcome(
    stage: OrchestrationStage, outcome: OrchestrationOutcome
) -> OrchestrationStatus:
    if outcome is OrchestrationOutcome.AWAITING_HUMAN:
        if stage is not OrchestrationStage.HUMAN_HANDOFF:
            raise RepositoryError("awaiting_human is only valid for human_handoff")
        return OrchestrationStatus.AWAITING_HUMAN
    if outcome is OrchestrationOutcome.FAILED:
        return OrchestrationStatus.FAILED
    if outcome is OrchestrationOutcome.REQUIRES_ATTENTION:
        return OrchestrationStatus.REQUIRES_ATTENTION
    return OrchestrationStatus.COMPLETED


__all__ = ["OrchestrationRepository", "OrchestrationRunRecord"]
