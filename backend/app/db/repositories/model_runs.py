"""Authoritative PostgreSQL repository for bounded model-analysis runs."""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.audit.model_analysis import ModelAnalysisAudit, ModelAnalysisPersistenceError

from .base import RepositoryError, TenantScopedRepository


class ModelRunRepository(TenantScopedRepository):
    """Persist only values constructed after T074 parsing and T075 validation.

    The model run and its proposal audit rows are written in the caller's
    PostgreSQL transaction.  No model output is sent to a connector or action
    gateway here, and no in-memory map is used as an authority.
    """

    def create(self, run: ModelAnalysisAudit) -> object:
        return self.persist(run)

    save = create
    append = create

    def persist(self, run: ModelAnalysisAudit) -> object:
        if not isinstance(run, ModelAnalysisAudit):
            raise TypeError("model run must be a ModelAnalysisAudit")
        if not run.validated:
            raise ModelAnalysisPersistenceError("unvalidated model analysis cannot be persisted")
        self.assert_tenant(run.tenant_id)
        row = self.fetch_one(
            """
            INSERT INTO public.model_runs (
                tenant_id, analysis_id, case_id, correlation_id, deterministic_seed,
                mode, replay_label,
                provider, model, adapter_version, request_schema_version,
                response_schema_version, parser_version, request_checksum,
                response_checksum, deterministic_analysis_checksum,
                deterministic_exposure_checksum, input_references, output_references,
                evidence_references, timeline_references, attribution_versions,
                feature_schema_version, exposure_version, exposure_currency,
                gross_exposure_minor, recoverable_value_minor, contained_value_minor,
                legitimate_value_disrupted_minor, irreversible_loss_minor,
                remaining_exposure_minor, uncertainty, refusal_records,
                forbidden_attempts, provenance, created_at,
                requested_mode, terminal_outcome, fallback_reason
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s
            )
            ON CONFLICT (tenant_id, analysis_id) DO NOTHING
            RETURNING tenant_id, analysis_id, case_id, mode, response_checksum,
                      deterministic_analysis_checksum
            """,
            (
                run.tenant_id,
                run.analysis_id,
                run.case_id,
                run.correlation_id,
                run.deterministic_seed,
                run.mode,
                run.replay_label,
                run.provider,
                run.model,
                run.adapter_version,
                run.request_schema_version,
                run.response_schema_version,
                run.parser_version,
                run.request_checksum,
                run.response_checksum,
                run.deterministic_analysis_checksum,
                run.deterministic_exposure_checksum,
                _array(run.input_references),
                _array(run.output_references),
                _array(run.evidence_references),
                _array(run.timeline_references),
                _array(run.attribution_versions),
                run.feature_schema_version,
                run.exposure_version,
                run.exposure_currency,
                run.gross_exposure_minor,
                run.recoverable_value_minor,
                run.contained_value_minor,
                run.legitimate_value_disrupted_minor,
                run.irreversible_loss_minor,
                run.remaining_exposure_minor,
                _json(run.uncertainty),
                _json(run.refusal_records),
                _json(run.forbidden_attempts),
                _json(run.provenance),
                run.created_at,
                run.requested_mode,
                run.terminal_outcome,
                run.fallback_reason,
            ),
        )
        if row is None:
            existing = self._existing_run(run)
            if existing is None:
                raise RepositoryError("model run disappeared after identity conflict")
            if not _same_run_identity(existing, run):
                raise RepositoryError("analysis identity conflicts with existing model run")
            self._assert_existing_proposals(run)
            return existing

        for proposal in run.proposals:
            proposal_row = self.fetch_one(
                """
                INSERT INTO public.model_run_proposals (
                    tenant_id, analysis_id, case_id, proposal_id, proposal_checksum,
                    validation_status, validation_version, validation_checksum,
                    authoritative_input_checksum, policy_evaluation_ready,
                    execution_state, approval_state, proposal, validation, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (tenant_id, analysis_id, proposal_id) DO NOTHING
                RETURNING tenant_id, analysis_id, proposal_id, validation_status
                """,
                (
                    run.tenant_id,
                    run.analysis_id,
                    run.case_id,
                    proposal.proposal.proposal_id,
                    proposal.proposal_checksum,
                    proposal.validation_status,
                    proposal.validation_version,
                    proposal.validation_checksum,
                    proposal.authoritative_input_checksum,
                    proposal.policy_evaluation_ready,
                    proposal.execution_state,
                    proposal.approval_state,
                    _json(proposal.proposal),
                    _json(proposal.as_dict()),
                    run.created_at,
                ),
            )
            if proposal_row is None:
                existing_proposal = self.fetch_one(
                    """
                    SELECT proposal_checksum, validation_checksum, validation_status,
                           case_id, execution_state, approval_state
                    FROM public.model_run_proposals
                    WHERE tenant_id = %s AND analysis_id = %s AND proposal_id = %s
                    """,
                    (run.tenant_id, run.analysis_id, proposal.proposal.proposal_id),
                )
                if existing_proposal is None or tuple(existing_proposal[:6]) != (
                    proposal.proposal_checksum,
                    proposal.validation_checksum,
                    proposal.validation_status,
                    run.case_id,
                    proposal.execution_state,
                    proposal.approval_state,
                ):
                    raise RepositoryError(
                        "proposal identity conflicts with existing model-run proposal"
                    )
        return row

    def get(self, *, analysis_id: str) -> object | None:
        _required_text(analysis_id, "analysis_id")
        return self.fetch_one(
            """
            SELECT tenant_id, analysis_id, case_id, correlation_id, deterministic_seed,
                   mode, replay_label,
                   provider, model, adapter_version, request_schema_version,
                   response_schema_version, parser_version, request_checksum,
                   response_checksum, deterministic_analysis_checksum,
                   deterministic_exposure_checksum, input_references, output_references,
                   evidence_references, timeline_references, attribution_versions,
                   feature_schema_version, exposure_version, exposure_currency,
                   gross_exposure_minor, recoverable_value_minor, contained_value_minor,
                   legitimate_value_disrupted_minor, irreversible_loss_minor,
                   remaining_exposure_minor, uncertainty, refusal_records,
                   forbidden_attempts, provenance, created_at,
                   requested_mode, terminal_outcome, fallback_reason
            FROM public.model_runs
            WHERE tenant_id = %s AND analysis_id = %s
            """,
            (self.tenant_context.tenant_id, analysis_id),
        )

    find = get

    def for_case(self, *, case_id: str) -> list[object]:
        _required_text(case_id, "case_id")
        return self.fetch_all(
            """
            SELECT tenant_id, analysis_id, case_id, correlation_id, deterministic_seed,
                   mode, replay_label,
                   provider, model, adapter_version, request_schema_version,
                   response_schema_version, parser_version, request_checksum,
                   response_checksum, deterministic_analysis_checksum,
                   deterministic_exposure_checksum, input_references, output_references,
                   evidence_references, timeline_references, attribution_versions,
                   feature_schema_version, exposure_version, exposure_currency,
                   gross_exposure_minor, recoverable_value_minor, contained_value_minor,
                   legitimate_value_disrupted_minor, irreversible_loss_minor,
                   remaining_exposure_minor, uncertainty, refusal_records,
                   forbidden_attempts, provenance, created_at,
                   requested_mode, terminal_outcome, fallback_reason
            FROM public.model_runs
            WHERE tenant_id = %s AND case_id = %s
            ORDER BY created_at, analysis_id
            """,
            (self.tenant_context.tenant_id, case_id),
        )

    def proposals(self, *, analysis_id: str) -> list[object]:
        _required_text(analysis_id, "analysis_id")
        return self.fetch_all(
            """
            SELECT tenant_id, analysis_id, case_id, proposal_id, proposal_checksum,
                   validation_status, validation_version, validation_checksum,
                   authoritative_input_checksum, policy_evaluation_ready,
                   execution_state, approval_state, proposal, validation, created_at
            FROM public.model_run_proposals
            WHERE tenant_id = %s AND analysis_id = %s
            ORDER BY proposal_id
            """,
            (self.tenant_context.tenant_id, analysis_id),
        )

    def _existing_run(self, run: ModelAnalysisAudit) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, analysis_id, case_id, correlation_id, deterministic_seed,
                   mode, replay_label,
                   provider, model, adapter_version, request_schema_version,
                   response_schema_version, parser_version, request_checksum,
                   response_checksum, deterministic_analysis_checksum,
                   deterministic_exposure_checksum,
                   requested_mode, terminal_outcome, fallback_reason
            FROM public.model_runs
            WHERE tenant_id = %s AND analysis_id = %s
            """,
            (run.tenant_id, run.analysis_id),
        )

    def _assert_existing_proposals(self, run: ModelAnalysisAudit) -> None:
        rows = self.proposals(analysis_id=run.analysis_id)
        if len(rows) != len(run.proposals):
            raise RepositoryError("existing model run has a conflicting proposal set")
        by_id = {str(row[3]): row for row in rows}
        for proposal in run.proposals:
            row = by_id.get(proposal.proposal.proposal_id)
            if row is None or tuple(row[4:12]) != (
                proposal.proposal_checksum,
                proposal.validation_status,
                proposal.validation_version,
                proposal.validation_checksum,
                proposal.authoritative_input_checksum,
                proposal.policy_evaluation_ready,
                proposal.execution_state,
                proposal.approval_state,
            ):
                raise RepositoryError("existing model run proposal content conflicts")

    def get_audit(self, *, analysis_id: str) -> ModelAnalysisAudit | None:
        """Read back the redacted authoritative model-analysis audit value."""

        row = self.get(analysis_id=analysis_id)
        if row is None:
            return None
        return ModelAnalysisAudit.from_persisted_row(
            row,
            proposal_rows=self.proposals(analysis_id=analysis_id),
        )


def _same_run_identity(row: Sequence[object], run: ModelAnalysisAudit) -> bool:
    # Columns match the SELECT in _existing_run.
    return tuple(row[0:17]) == (
        run.tenant_id,
        run.analysis_id,
        run.case_id,
        run.correlation_id,
        run.deterministic_seed,
        run.mode,
        run.replay_label,
        run.provider,
        run.model,
        run.adapter_version,
        run.request_schema_version,
        run.response_schema_version,
        run.parser_version,
        run.request_checksum,
        run.response_checksum,
        run.deterministic_analysis_checksum,
        run.deterministic_exposure_checksum,
    ) and tuple(row[17:20]) == (
        run.requested_mode,
        run.terminal_outcome,
        run.fallback_reason,
    )


def _array(values: Sequence[str]) -> list[str]:
    return list(values)


def _json(value: object) -> str:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"model run repository {name} is required")
    return value.strip()


__all__ = ["ModelRunRepository"]
