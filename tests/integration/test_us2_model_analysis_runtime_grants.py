"""US2 runtime-grant and non-owner model-analysis persistence qualification."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from acceptance.test_attribution_exposure_analysis import (
    CASE_ID as CANONICAL_CASE_ID,
    CORRELATION_ID as CANONICAL_CORRELATION_ID,
    TENANT_ID as CANONICAL_TENANT_ID,
    _prepared_case,
    _run,
)
from analysis.deterministic_summary import run_us2_analysis
from analysis.proposal_validator import ProposalValidator
from app.audit.model_analysis import ModelAnalysisAudit, ModelAnalysisPersistenceError
from app.db.repositories.model_runs import ModelRunRepository
from app.db.repositories.base import RepositoryError
from app.db.tenant_context import TenantContext
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from integration.test_us2_analysis_exposure import _validation_context


pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "backend" / "db" / "migrations"
MIGRATION_NAMES = tuple(
    f"{number:03d}_{name}.sql"
    for number, name in (
        (1, "authoritative_entities"),
        (2, "tenant_isolation"),
        (3, "batch_b_integrity"),
        (4, "final_gate_integrity"),
        (5, "provider_correlation_authority"),
        (6, "provider_correlation_schema"),
        (7, "model_analysis_runs"),
        (8, "model_analysis_runtime_grants"),
    )
)
MODEL_TABLES = ("public.model_runs", "public.model_run_proposals")
REQUIRED_PRIVILEGES = {"SELECT", "INSERT"}
FORBIDDEN_RUNTIME_PRIVILEGES = {
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
}


@dataclass(frozen=True, slots=True)
class Seed:
    tenant_a: str
    tenant_b: str
    case_a1: str
    case_a2: str
    case_b1: str
    incident_a1: str
    incident_a2: str
    incident_b1: str


def _admin_url() -> str:
    value = os.getenv("RECLAIM_MODEL_ANALYSIS_MIGRATION_DATABASE_URL")
    if not value:
        pytest.skip(
            "RECLAIM_MODEL_ANALYSIS_MIGRATION_DATABASE_URL is required for fresh PostgreSQL validation"
        )
    return value


def _runtime_url() -> str:
    value = os.getenv("RECLAIM_MODEL_ANALYSIS_RLS_DATABASE_URL")
    if not value:
        pytest.skip(
            "RECLAIM_MODEL_ANALYSIS_RLS_DATABASE_URL is required for reclaim_app validation"
        )
    return value


def _apply_migrations(connection: Any, *, search_path: str = "public") -> None:
    connection.execute(f"SET LOCAL search_path TO {search_path}")
    for migration_name in MIGRATION_NAMES:
        connection.execute((MIGRATIONS / migration_name).read_text(encoding="utf-8"))


def _set_tenant(connection: Any, tenant_id: str) -> None:
    connection.execute(
        "SELECT set_config('reclaim.tenant_id', %s, true)",
        (tenant_id,),
    )


def _authorization_context(tenant_id: str) -> TenantAuthorizationContext:
    return TenantAuthorizationContext(
        subject="reclaim-app-us2-runtime-grants",
        tenant_id=tenant_id,
        roles=frozenset({"reviewer"}),
        identity_type=IdentityType.SERVICE,
        issuer="https://issuer.reclaim.test",
    )


def _seed(connection: Any) -> Seed:
    suffix = uuid4().hex
    seed = Seed(
        tenant_a=f"us2-grants-a-{suffix}",
        tenant_b=f"us2-grants-b-{suffix}",
        case_a1=f"us2-grants-a1-{suffix}",
        case_a2=f"us2-grants-a2-{suffix}",
        case_b1=f"us2-grants-b1-{suffix}",
        incident_a1=f"us2-grants-incident-a1-{suffix}",
        incident_a2=f"us2-grants-incident-a2-{suffix}",
        incident_b1=f"us2-grants-incident-b1-{suffix}",
    )
    for tenant_id in (seed.tenant_a, seed.tenant_b):
        connection.execute(
            "INSERT INTO public.tenants (tenant_id, display_name) VALUES (%s, %s)",
            (tenant_id, tenant_id),
        )
    for tenant_id, incident_id, case_id in (
        (seed.tenant_a, seed.incident_a1, seed.case_a1),
        (seed.tenant_a, seed.incident_a2, seed.case_a2),
        (seed.tenant_b, seed.incident_b1, seed.case_b1),
    ):
        connection.execute(
            """
            INSERT INTO public.incidents (
                tenant_id, incident_id, source, received_at, correlation_key,
                intake_status, deduplication_identity
            ) VALUES (%s, %s, 'us2-runtime-grants', %s, %s, 'accepted', %s)
            """,
            (
                tenant_id,
                incident_id,
                datetime(2026, 9, 1, 10, tzinfo=UTC),
                f"correlation-{incident_id}",
                f"dedupe-{incident_id}",
            ),
        )
        connection.execute(
            """
            INSERT INTO public.cases (
                tenant_id, case_id, incident_id, current_state
            ) VALUES (%s, %s, %s, 'timeline_ready')
            """,
            (tenant_id, case_id, incident_id),
        )
    return seed


def _cleanup(
    connection: Any, seed: Seed, audit: ModelAnalysisAudit | None = None
) -> None:
    tenant_ids = (seed.tenant_a, seed.tenant_b)
    placeholders = ", ".join("%s" for _ in tenant_ids)
    connection.execute(
        f"DELETE FROM public.model_run_proposals WHERE tenant_id IN ({placeholders})",
        tenant_ids,
    )
    connection.execute(
        f"DELETE FROM public.model_runs WHERE tenant_id IN ({placeholders})",
        tenant_ids,
    )
    if audit is not None:
        connection.execute(
            "DELETE FROM public.model_run_proposals WHERE tenant_id = %s",
            (audit.tenant_id,),
        )
        connection.execute(
            "DELETE FROM public.model_runs WHERE tenant_id = %s",
            (audit.tenant_id,),
        )
    all_tenants = (*tenant_ids, CANONICAL_TENANT_ID)
    all_placeholders = ", ".join("%s" for _ in all_tenants)
    connection.execute(
        f"DELETE FROM public.cases WHERE tenant_id IN ({all_placeholders})",
        all_tenants,
    )
    connection.execute(
        f"DELETE FROM public.incidents WHERE tenant_id IN ({all_placeholders})",
        all_tenants,
    )
    connection.execute(
        f"DELETE FROM public.tenants WHERE tenant_id IN ({all_placeholders})",
        all_tenants,
    )


def _build_canonical_audit() -> tuple[Any, ModelAnalysisAudit]:
    evidence, timeline = _prepared_case()
    result = _run(run_us2_analysis, evidence, timeline)
    proposal = result.analysis_response.proposals[0]
    validation = ProposalValidator().validate(
        proposal,
        _validation_context(result, evidence, timeline),
    )
    return result, ModelAnalysisAudit.from_result(
        result,
        proposal_validations={proposal.proposal_id: validation},
        created_at=datetime(2026, 9, 1, 10, tzinfo=UTC),
    )


def _assert_sql_denied(
    connection: Any,
    psycopg: Any,
    query: str,
    params: tuple[object, ...] = (),
) -> None:
    savepoint = f"us2_runtime_denial_{uuid4().hex}"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        with pytest.raises(psycopg.Error):
            connection.execute(query, params)
    finally:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def test_migration_008_is_scoped_to_model_analysis_runtime_operations() -> None:
    migration = (MIGRATIONS / "008_model_analysis_runtime_grants.sql").read_text(
        encoding="utf-8"
    )
    assert "public.model_runs" in migration
    assert "public.model_run_proposals" in migration
    assert (
        "REVOKE ALL ON TABLE public.model_runs, public.model_run_proposals FROM PUBLIC"
        in migration
    )
    assert (
        "GRANT SELECT, INSERT ON TABLE public.model_runs, public.model_run_proposals TO reclaim_app"
        in migration
    )
    assert "GRANT UPDATE" not in migration
    assert "GRANT DELETE" not in migration
    assert "GRANT ALL" not in migration
    assert "reclaim.require_tenant_context()" in migration


def test_fresh_migrations_001_to_008_are_search_path_independent_and_idempotent() -> (
    None
):
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(_admin_url())
    try:
        connection.execute("BEGIN")
        _apply_migrations(connection)
        connection.execute("SET LOCAL search_path TO reclaim, public")
        connection.execute(
            (MIGRATIONS / "008_model_analysis_runtime_grants.sql").read_text(
                encoding="utf-8"
            )
        )

        assert connection.execute(
            "SELECT to_regclass('public.model_runs'), to_regclass('public.model_run_proposals')"
        ).fetchone() == ("model_runs", "model_run_proposals")
        assert connection.execute(
            "SELECT to_regclass('reclaim.model_runs'), to_regclass('reclaim.model_run_proposals')"
        ).fetchone() == (None, None)
        assert connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reclaim_app')"
        ).fetchone() == (True,)

        # Applying the corrective migration again must preserve the same ACLs.
        connection.execute(
            (MIGRATIONS / "008_model_analysis_runtime_grants.sql").read_text(
                encoding="utf-8"
            )
        )
        for table_name in MODEL_TABLES:
            assert connection.execute(
                "SELECT has_table_privilege('reclaim_app', %s, 'SELECT'), "
                "has_table_privilege('reclaim_app', %s, 'INSERT'), "
                "has_table_privilege('reclaim_app', %s, 'UPDATE'), "
                "has_table_privilege('reclaim_app', %s, 'DELETE')",
                (table_name, table_name, table_name, table_name),
            ).fetchone() == (True, True, False, False)
    finally:
        connection.rollback()
        connection.close()


def test_reclaim_app_runtime_privileges_rls_and_persistence_boundary() -> None:
    psycopg = pytest.importorskip("psycopg")
    admin = psycopg.connect(_admin_url())
    runtime = psycopg.connect(_runtime_url())
    seed: Seed | None = None
    audit: ModelAnalysisAudit | None = None
    try:
        admin.execute("BEGIN")
        # This is safe on the disposable qualification database and also supports
        # validating a database that already contains migration 007.
        _apply_migrations(admin)
        seed = _seed(admin)
        admin.commit()

        role_state = runtime.execute(
            """
            SELECT current_user, current_role_info.rolsuper,
                   current_role_info.rolbypassrls,
                   table_owner.rolname
            FROM pg_roles AS current_role_info
            JOIN pg_class AS relation
              ON relation.oid IN ('public.model_runs'::regclass, 'public.model_run_proposals'::regclass)
            JOIN pg_roles AS table_owner ON table_owner.oid = relation.relowner
            WHERE current_role_info.rolname = current_user
            ORDER BY relation.relname
            LIMIT 1
            """
        ).fetchone()
        assert role_state is not None
        assert role_state[0:3] == ("reclaim_app", False, False)
        assert role_state[3] != role_state[0]

        for table_name in MODEL_TABLES:
            rls_state = runtime.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = %s::regclass",
                (table_name,),
            ).fetchone()
            assert rls_state == (True, True)
            privileges = runtime.execute(
                """
                SELECT privilege
                FROM (
                    SELECT unnest(ARRAY[
                        'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
                        'REFERENCES', 'TRIGGER'
                    ]) AS privilege
                ) AS expected
                WHERE has_table_privilege(current_user, %s, privilege)
                ORDER BY privilege
                """,
                (table_name,),
            ).fetchall()
            granted = {row[0] for row in privileges}
            assert granted == REQUIRED_PRIVILEGES
            assert granted.isdisjoint(FORBIDDEN_RUNTIME_PRIVILEGES)
        runtime.rollback()

        result, audit = _build_canonical_audit()
        assert result.tenant_id == CANONICAL_TENANT_ID
        assert result.case_id == CANONICAL_CASE_ID
        assert result.correlation_id == CANONICAL_CORRELATION_ID
        assert result.exposure.currency == "INR"
        assert result.exposure.gross_exposure_minor == 129_900
        assert result.uncertainty
        assert audit.mode == audit.replay_label == "replay"
        assert audit.provenance["authoritative_store"] == "postgresql"
        assert audit.provenance["side_effects"] is False

        # The canonical audit uses stable IDs; seed its tenant/case through the
        # owner connection before using only reclaim_app for persistence.
        admin.execute("BEGIN")
        admin.execute(
            "INSERT INTO public.tenants (tenant_id, display_name) VALUES (%s, %s)",
            (CANONICAL_TENANT_ID, CANONICAL_TENANT_ID),
        )
        admin.execute(
            """
            INSERT INTO public.incidents (
                tenant_id, incident_id, source, received_at, correlation_key,
                intake_status, deduplication_identity
            ) VALUES (%s, %s, 'us2-runtime-grants', %s, %s, 'accepted', %s)
            """,
            (
                CANONICAL_TENANT_ID,
                f"incident-{CANONICAL_TENANT_ID}",
                datetime(2026, 9, 1, 10, tzinfo=UTC),
                f"correlation-{CANONICAL_TENANT_ID}",
                f"dedupe-{CANONICAL_TENANT_ID}",
            ),
        )
        admin.execute(
            """
            INSERT INTO public.cases (
                tenant_id, case_id, incident_id, current_state
            ) VALUES (%s, %s, %s, 'timeline_ready')
            """,
            (
                CANONICAL_TENANT_ID,
                CANONICAL_CASE_ID,
                f"incident-{CANONICAL_TENANT_ID}",
            ),
        )
        admin.commit()

        runtime.execute("BEGIN")
        _set_tenant(runtime, CANONICAL_TENANT_ID)
        repository = ModelRunRepository(
            runtime,
            TenantContext.from_authorization_context(
                _authorization_context(CANONICAL_TENANT_ID)
            ),
        )
        first_row = repository.persist(audit)
        retry_row = repository.persist(audit)
        assert tuple(retry_row[index] for index in (0, 1, 2, 5, 14, 15)) == first_row
        assert repository.get(analysis_id=audit.analysis_id) is not None
        proposal_rows = repository.proposals(analysis_id=audit.analysis_id)
        assert len(proposal_rows) == len(audit.proposals)
        assert proposal_rows[0][0:4] == (
            audit.tenant_id,
            audit.analysis_id,
            audit.case_id,
            audit.proposals[0].proposal.proposal_id,
        )
        stored = runtime.execute(
            """
            SELECT tenant_id, case_id, mode, replay_label, exposure_currency,
                   gross_exposure_minor, recoverable_value_minor,
                   contained_value_minor, legitimate_value_disrupted_minor,
                   irreversible_loss_minor, remaining_exposure_minor,
                   uncertainty, request_checksum, response_checksum,
                   deterministic_analysis_checksum, deterministic_exposure_checksum,
                   provenance
            FROM public.model_runs
            WHERE tenant_id = %s AND analysis_id = %s
            """,
            (audit.tenant_id, audit.analysis_id),
        ).fetchone()
        assert stored is not None
        assert stored[0:5] == (
            audit.tenant_id,
            audit.case_id,
            "replay",
            "replay",
            "INR",
        )
        assert stored[5:11] == (
            audit.gross_exposure_minor,
            audit.recoverable_value_minor,
            audit.contained_value_minor,
            audit.legitimate_value_disrupted_minor,
            audit.irreversible_loss_minor,
            audit.remaining_exposure_minor,
        )
        assert tuple(stored[11]) == audit.uncertainty
        assert stored[12:16] == (
            audit.request_checksum,
            audit.response_checksum,
            audit.deterministic_analysis_checksum,
            audit.deterministic_exposure_checksum,
        )
        assert stored[16] == audit.provenance

        changed = replace(
            audit, provider="changed-provider", response_checksum="f" * 64
        )
        with pytest.raises(RepositoryError, match="conflicts"):
            repository.persist(changed)
        cross_case_audit = replace(audit, case_id=seed.case_a2)
        with pytest.raises(RepositoryError, match="conflicts"):
            repository.persist(cross_case_audit)

        # The model boundary rejects an unvalidated value before touching the DB.
        before = runtime.execute(
            "SELECT count(*) FROM public.model_runs WHERE tenant_id = %s",
            (CANONICAL_TENANT_ID,),
        ).fetchone()
        with pytest.raises(ModelAnalysisPersistenceError, match="validation result"):
            ModelAnalysisAudit.from_result(result)
        assert (
            runtime.execute(
                "SELECT count(*) FROM public.model_runs WHERE tenant_id = %s",
                (CANONICAL_TENANT_ID,),
            ).fetchone()
            == before
        )

        # Tenant A cannot see Tenant B's model-analysis rows.
        admin.execute("BEGIN")
        admin.execute(
            """
            INSERT INTO public.model_runs (
                tenant_id, analysis_id, case_id, correlation_id, deterministic_seed,
                mode, replay_label, provider, model, adapter_version,
                request_schema_version, response_schema_version, parser_version,
                request_checksum, response_checksum, deterministic_analysis_checksum,
                deterministic_exposure_checksum, exposure_version, exposure_currency,
                gross_exposure_minor, recoverable_value_minor, contained_value_minor,
                legitimate_value_disrupted_minor, irreversible_loss_minor,
                remaining_exposure_minor, provenance
            ) VALUES (%s, 'analysis-b', %s, 'correlation-b', 'seed-b', 'replay',
                      'replay', 'provider-b', 'model-b', 'adapter-b', '1.0.0',
                      '1.0.0', 'parser-b', repeat('b', 64), repeat('c', 64),
                      repeat('d', 64), repeat('e', 64), 'exposure-b', 'INR',
                      100, 80, 20, 0, 20, 60, '{}'::jsonb)
            """,
            (seed.tenant_b, seed.case_b1),
        )
        admin.execute(
            """
            INSERT INTO public.model_run_proposals (
                tenant_id, analysis_id, case_id, proposal_id, proposal_checksum,
                validation_status, validation_version, validation_checksum,
                authoritative_input_checksum, policy_evaluation_ready, proposal,
                validation
            ) VALUES (%s, 'analysis-b', %s, 'proposal-b', repeat('f', 64),
                      'rejected', 'validation-b', repeat('a', 64), repeat('b', 64),
                      false, '{}'::jsonb, '{}'::jsonb)
            """,
            (seed.tenant_b, seed.case_b1),
        )
        admin.commit()

        assert runtime.execute(
            "SELECT count(*) FROM public.model_runs WHERE tenant_id = %s",
            (seed.tenant_b,),
        ).fetchone() == (0,)
        assert runtime.execute(
            "SELECT count(*) FROM public.model_run_proposals WHERE tenant_id = %s",
            (seed.tenant_b,),
        ).fetchone() == (0,)

        # Cross-tenant writes are rejected by forced tenant RLS.
        _assert_sql_denied(
            runtime,
            psycopg,
            """
            INSERT INTO public.model_runs (
                tenant_id, analysis_id, case_id, correlation_id, deterministic_seed,
                mode, replay_label, provider, model, adapter_version,
                request_schema_version, response_schema_version, parser_version,
                request_checksum, response_checksum, deterministic_analysis_checksum,
                deterministic_exposure_checksum, exposure_version, exposure_currency,
                gross_exposure_minor, recoverable_value_minor, contained_value_minor,
                legitimate_value_disrupted_minor, irreversible_loss_minor,
                remaining_exposure_minor, provenance
            ) VALUES (%s, 'analysis-cross-tenant', %s, 'correlation-cross-tenant',
                      'seed', 'replay', 'replay', 'provider', 'model', 'adapter',
                      '1.0.0', '1.0.0', 'parser', repeat('1', 64), repeat('2', 64),
                      repeat('3', 64), repeat('4', 64), 'exposure', 'INR',
                      100, 80, 20, 0, 20, 60, '{}'::jsonb)
            """,
            (seed.tenant_b, seed.case_b1),
        )
        _assert_sql_denied(
            runtime,
            psycopg,
            """
            INSERT INTO public.model_run_proposals (
                tenant_id, analysis_id, case_id, proposal_id, proposal_checksum,
                validation_status, validation_version, validation_checksum,
                authoritative_input_checksum, policy_evaluation_ready, proposal,
                validation
            ) VALUES (%s, %s, %s, 'proposal-cross-tenant', repeat('1', 64),
                      'rejected', 'validation', repeat('2', 64), repeat('3', 64),
                      false, '{}'::jsonb, '{}'::jsonb)
            """,
            (seed.tenant_b, audit.analysis_id, seed.case_b1),
        )

        # A proposal cannot bind the Tenant-A analysis to Tenant-A Case A2;
        # the composite model-run FK requires the exact case identity.
        _assert_sql_denied(
            runtime,
            psycopg,
            """
            INSERT INTO public.model_run_proposals (
                tenant_id, analysis_id, case_id, proposal_id, proposal_checksum,
                validation_status, validation_version, validation_checksum,
                authoritative_input_checksum, policy_evaluation_ready, proposal,
                validation
            ) VALUES (%s, %s, %s, 'proposal-cross-case', repeat('1', 64),
                      'rejected', 'validation', repeat('2', 64), repeat('3', 64),
                      false, '{}'::jsonb, '{}'::jsonb)
            """,
            (audit.tenant_id, audit.analysis_id, seed.case_a2),
        )

        _assert_sql_denied(
            runtime,
            psycopg,
            "UPDATE public.model_runs SET provider = 'changed' WHERE tenant_id = %s",
            (seed.tenant_b,),
        )
        _assert_sql_denied(
            runtime,
            psycopg,
            "DELETE FROM public.model_runs WHERE tenant_id = %s",
            (audit.tenant_id,),
        )
        _assert_sql_denied(
            runtime,
            psycopg,
            "DELETE FROM public.model_run_proposals WHERE tenant_id = %s",
            (audit.tenant_id,),
        )
        runtime.rollback()
    finally:
        runtime.close()
        if seed is not None:
            admin.execute("BEGIN")
            _cleanup(admin, seed, audit)
            admin.commit()
        admin.close()
