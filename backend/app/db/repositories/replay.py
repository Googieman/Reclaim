"""Authoritative replay and evaluation metadata repositories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import json

from .base import TenantScopedRepository


class ReplayRunRepository(TenantScopedRepository):
    def create(
        self,
        *,
        run_id: str,
        fixture_version: str,
        connector_simulator_version: str,
        action_simulator_version: str,
        policy_version_id: str,
        model_provider_mode: str,
        deterministic_seed: int,
        environment_metadata: Mapping[str, object],
        mode: str,
        stage_outcomes: Mapping[str, str],
        label: str = "replay",
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO replay_runs (
                tenant_id, run_id, fixture_version, connector_simulator_version,
                action_simulator_version, policy_version_id, model_provider_mode,
                deterministic_seed, environment_metadata, mode, stage_outcomes, label
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
            RETURNING tenant_id, run_id, mode, label, deterministic_seed
            """,
            (
                self.tenant_context.tenant_id,
                run_id,
                fixture_version,
                connector_simulator_version,
                action_simulator_version,
                policy_version_id,
                model_provider_mode,
                deterministic_seed,
                json.dumps(environment_metadata, sort_keys=True, separators=(",", ":")),
                mode,
                json.dumps(stage_outcomes, sort_keys=True, separators=(",", ":")),
                label,
            ),
        )
        if row is None:
            raise RuntimeError("replay run insert returned no row")
        return row


class EvaluationCaseRepository(TenantScopedRepository):
    def create(
        self,
        *,
        evaluation_case_id: str,
        provenance: Mapping[str, object],
        label_source: str,
        split: str,
        entity_group_id: str,
        customer_group_id: str | None,
        temporal_boundary: datetime,
        class_labels: Sequence[str],
        no_compromise_false_alert: bool,
        mixed_legitimate_malicious: bool,
        expected_outcomes: Mapping[str, object],
        leakage_checks: Mapping[str, bool],
        held_out_access_policy: str,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO evaluation_cases (
                tenant_id, evaluation_case_id, provenance, label_source, split,
                entity_group_id, customer_group_id, temporal_boundary, class_labels,
                no_compromise_false_alert, mixed_legitimate_malicious,
                expected_outcomes, leakage_checks, held_out_access_policy
            )
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                    %s::jsonb, %s::jsonb, %s)
            RETURNING tenant_id, evaluation_case_id, split, entity_group_id
            """,
            (
                self.tenant_context.tenant_id,
                evaluation_case_id,
                json.dumps(provenance, sort_keys=True, separators=(",", ":")),
                label_source,
                split,
                entity_group_id,
                customer_group_id,
                temporal_boundary,
                json.dumps(list(class_labels), separators=(",", ":")),
                no_compromise_false_alert,
                mixed_legitimate_malicious,
                json.dumps(expected_outcomes, sort_keys=True, separators=(",", ":")),
                json.dumps(leakage_checks, sort_keys=True, separators=(",", ":")),
                held_out_access_policy,
            ),
        )
        if row is None:
            raise RuntimeError("evaluation case insert returned no row")
        return row
