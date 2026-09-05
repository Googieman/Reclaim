"""Deterministic, read-only release preflight for the RECLAIM repository.

The preflight is deliberately static by default.  It checks repository-owned
configuration and reviewed evidence, but does not start containers, contact a
merchant/provider, or print secret values.  A deployment-owned release
metadata file and production environment file may be supplied for validation;
only their key names and digest shape are reported.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class GateStatus(str, Enum):
    PASS = "PASS"
    OPEN = "OPEN"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class Gate:
    name: str
    status: GateStatus
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    gates: tuple[Gate, ...]

    def find(self, name: str) -> Gate:
        """Return a named gate, failing loudly when the contract changes."""

        for gate in self.gates:
            if gate.name == name:
                return gate
        raise KeyError(name)

    @property
    def summary(self) -> str:
        if any(gate.status is GateStatus.BLOCK for gate in self.gates):
            return "NO-GO"
        if any(gate.status is GateStatus.OPEN for gate in self.gates):
            return "CONDITIONAL NO-GO"
        return "GO"

    @property
    def exit_code(self) -> int:
        return 0 if self.summary == "GO" else 2

    def render(self) -> tuple[str, ...]:
        return tuple(
            f"[{gate.status.value}] {gate.name}: {gate.detail}" for gate in self.gates
        ) + (f"DECISION: {self.summary}",)


REQUIRED_PRODUCTION_INPUTS = (
    "RECLAIM_API_IMAGE",
    "RECLAIM_WEB_IMAGE",
    "KEYCLOAK_HOSTNAME",
    "RECLAIM_OIDC_AUDIENCE",
    "RECLAIM_OIDC_JWKS_URL",
    "RECLAIM_VAULT_ADDRESS",
    "RECLAIM_REDPANDA_SASL_USERNAME",
    "RECLAIM_REDPANDA_TLS_DIR",
    "RECLAIM_SECRET_DIR",
    "RECLAIM_CONTROL_PLANE_TLS_DIR",
    "N8N_HOST",
    "N8N_DB_PASSWORD",
    "N8N_ENCRYPTION_KEY",
    "RECLAIM_N8N_SERVICE_TOKEN",
    "KEYCLOAK_DB_USERNAME",
    "KEYCLOAK_DB_PASSWORD",
)

REQUIRED_PINNED_VERSIONS = (
    "PYTHON_VERSION",
    "NODE_VERSION",
    "POSTGRES_VERSION",
    "TEMPORAL_VERSION",
    "N8N_VERSION",
    "REDPANDA_VERSION",
    "NEO4J_VERSION",
    "MINIO_VERSION",
    "REDIS_VERSION",
    "KEYCLOAK_VERSION",
    "VAULT_VERSION",
    "OTEL_COLLECTOR_VERSION",
    "PROMETHEUS_VERSION",
    "GRAFANA_VERSION",
    "LOKI_VERSION",
    "LANGFUSE_VERSION",
    "MLFLOW_VERSION",
)

REQUIRED_FILES = (
    "infra/versions.env",
    "infra/docker-compose.yml",
    "infra/docker-compose.production.yml",
    "infra/backup/policy.yml",
    "infra/observability/alerts.yml",
    "infra/observability/grafana/dashboards/operations.json",
    "scripts/build_provenance.py",
    "scripts/release-preflight.ps1",
    "scripts/release_preflight.py",
    "scripts/backup-postgres.ps1",
    "scripts/restore-postgres.ps1",
    "scripts/backup-minio.ps1",
    "scripts/restore-minio.ps1",
    "docs/operator/deployment.md",
    "docs/operator/backup-restore.md",
    "docs/operator/migration-rehearsal.md",
    "docs/operator/release-readiness.md",
    "backend/db/migrations/013_incident_intake_n8n.sql",
    ".github/workflows/ci.yml",
    ".github/workflows/security.yml",
    ".github/workflows/evaluation.yml",
)


def _text(root: Path, relative: str) -> str | None:
    path = root / relative
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _parse_env_names(path: Path) -> tuple[set[str], set[str], set[str]]:
    names: set[str] = set()
    placeholders: set[str] = set()
    invalid_immutable_images: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^export\s+", "", line)
        name, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.strip()):
            continue
        normalized_name = name.strip()
        names.add(normalized_name)
        normalized_value = value.strip().strip('"').strip("'").lower()
        if not normalized_value or any(
            marker in normalized_value
            for marker in ("configure-out-of-band", "change-me", "example.internal")
        ):
            placeholders.add(normalized_name)
        if normalized_name in {
            "RECLAIM_API_IMAGE",
            "RECLAIM_WEB_IMAGE",
        } and not re.fullmatch(r".+@sha256:[0-9a-f]{64}", normalized_value):
            invalid_immutable_images.add(normalized_name)
    return names, placeholders, invalid_immutable_images


def _parse_pins(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        pins[name.strip()] = value.strip()
    return pins


def _required_files_gate(root: Path) -> Gate:
    missing = tuple(
        relative for relative in REQUIRED_FILES if _text(root, relative) is None
    )
    if missing:
        return Gate(
            "required-artifacts",
            GateStatus.BLOCK,
            f"missing {len(missing)} required repository artifacts",
        )
    return Gate(
        "required-artifacts",
        GateStatus.PASS,
        f"{len(REQUIRED_FILES)} required repository artifacts present",
    )


def _release_metadata_gate(root: Path, metadata_path: Path | None) -> Gate:
    if metadata_path is None:
        return Gate(
            "release-metadata",
            GateStatus.OPEN,
            "deployment-owned release metadata artifact was not supplied",
        )
    if not metadata_path.is_file():
        return Gate(
            "release-metadata",
            GateStatus.BLOCK,
            "supplied release metadata artifact is missing",
        )
    try:
        metadata: Any = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Gate(
            "release-metadata", GateStatus.BLOCK, "release metadata is not valid JSON"
        )
    if not isinstance(metadata, dict):
        return Gate(
            "release-metadata",
            GateStatus.BLOCK,
            "release metadata root must be an object",
        )
    release_id = metadata.get("release_id")
    source_commit = metadata.get("source_commit")
    api_digest = metadata.get("api_image_digest")
    web_digest = metadata.get("web_image_digest")
    provenance = metadata.get("provenance")
    valid = (
        isinstance(release_id, str)
        and bool(release_id.strip())
        and release_id.lower() not in {"unversioned", "latest", "dev"}
        and isinstance(source_commit, str)
        and bool(re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", source_commit))
        and isinstance(api_digest, str)
        and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", api_digest))
        and isinstance(web_digest, str)
        and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", web_digest))
        and provenance == "scripts/build_provenance.py"
        and (root / str(provenance)).is_file()
    )
    if not valid:
        return Gate(
            "release-metadata",
            GateStatus.BLOCK,
            "release id, source commit, image digests, or provenance is invalid",
        )
    return Gate(
        "release-metadata",
        GateStatus.PASS,
        "release id, source commit, image digests, and provenance shape verified",
    )


def _pinned_versions_gate(root: Path) -> Gate:
    text = _text(root, "infra/versions.env")
    if text is None:
        return Gate("pinned-versions", GateStatus.BLOCK, "version pin file is missing")
    pins = _parse_pins(text)
    missing = tuple(name for name in REQUIRED_PINNED_VERSIONS if not pins.get(name))
    unsafe = tuple(
        name
        for name in REQUIRED_PINNED_VERSIONS
        if any(
            marker in pins.get(name, "").lower()
            for marker in ("latest", "dev", "change-me")
        )
    )
    if missing or unsafe:
        return Gate(
            "pinned-versions",
            GateStatus.BLOCK,
            "version pin inventory is incomplete or contains mutable markers",
        )
    dockerfiles = (_text(root, "backend/Dockerfile") or "") + (
        _text(root, "frontend/Dockerfile") or ""
    )
    if "python:3.12.8" not in dockerfiles or "node:22.14.0" not in dockerfiles:
        return Gate(
            "pinned-versions",
            GateStatus.BLOCK,
            "application Dockerfiles do not match the pinned runtime versions",
        )
    return Gate(
        "pinned-versions",
        GateStatus.PASS,
        f"{len(REQUIRED_PINNED_VERSIONS)} infrastructure versions and application runtimes are pinned",
    )


def _production_profile_gate(root: Path) -> Gate:
    text = _text(root, "infra/docker-compose.production.yml")
    if text is None:
        return Gate(
            "production-profile",
            GateStatus.BLOCK,
            "production Compose overlay is missing",
        )
    required_fragments = (
        "RECLAIM_ENVIRONMENT: production",
        'RECLAIM_LIVE_ACTIONS_ENABLED: "false"',
        'RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED: "false"',
        "RECLAIM_REDPANDA_SECURITY_PROTOCOL: SASL_SSL",
        "RECLAIM_REDPANDA_SASL_MECHANISM: SCRAM-SHA-512",
        "N8N_PROTOCOL: https",
        'N8N_SECURE_COOKIE: "true"',
        "profiles: [production]",
    )
    required_inputs = tuple(f"{name}:?" for name in REQUIRED_PRODUCTION_INPUTS)
    if any(fragment not in text for fragment in required_fragments):
        return Gate(
            "production-profile",
            GateStatus.BLOCK,
            "production overlay is missing a secure profile or disabled-action invariant",
        )
    if any(not name_is_interpolated(fragment, text) for fragment in required_inputs):
        return Gate(
            "production-profile",
            GateStatus.BLOCK,
            "production overlay has an incomplete required-input declaration",
        )
    if ":latest" in text.lower() or "-dev" in text.lower():
        return Gate(
            "production-profile",
            GateStatus.BLOCK,
            "production overlay contains a mutable development image marker",
        )
    return Gate(
        "production-profile",
        GateStatus.PASS,
        "production overlay is secure-profiled and fail-closed for live actions",
    )


def name_is_interpolated(fragment: str, text: str) -> bool:
    """Return whether the named required input has a `:?` Compose guard."""

    name = fragment.removesuffix(":?")
    return f"${{{name}:?" in text


def _production_inputs_gate(production_env: Path | None) -> Gate:
    if production_env is None:
        return Gate(
            "production-inputs",
            GateStatus.OPEN,
            "production secret-manager input file was not supplied; required values remain out-of-band",
        )
    if not production_env.is_file():
        return Gate(
            "production-inputs",
            GateStatus.BLOCK,
            "supplied production input file is missing",
        )
    try:
        names, placeholders, invalid_immutable_images = _parse_env_names(production_env)
    except OSError:
        return Gate(
            "production-inputs",
            GateStatus.BLOCK,
            "production input file could not be read",
        )
    missing = tuple(name for name in REQUIRED_PRODUCTION_INPUTS if name not in names)
    unsafe = tuple(name for name in REQUIRED_PRODUCTION_INPUTS if name in placeholders)
    if missing or unsafe or invalid_immutable_images:
        return Gate(
            "production-inputs",
            GateStatus.BLOCK,
            "required production input names are missing or still placeholders",
        )
    return Gate(
        "production-inputs",
        GateStatus.PASS,
        "all required production input names are present; values were not inspected for output",
    )


def _safe_defaults_gate(root: Path) -> Gate:
    paths = (
        "infra/.env.example",
        "infra/docker-compose.yml",
        "infra/docker-compose.production.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/security.yml",
        ".github/workflows/evaluation.yml",
    )
    combined = "\n".join(_text(root, path) or "" for path in paths)
    required = (
        "RECLAIM_LIVE_ACTIONS_ENABLED=false",
        "RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED=false",
    )
    if any(value not in combined.replace('"', "") for value in required):
        return Gate(
            "safe-defaults",
            GateStatus.BLOCK,
            "live-action defaults are not consistently disabled",
        )
    if re.search(
        r"RECLAIM_LIVE_(?:FINANCIAL_)?ACTIONS_ENABLED\s*[:=]\s*true",
        combined,
        re.IGNORECASE,
    ):
        return Gate(
            "safe-defaults",
            GateStatus.BLOCK,
            "a checked-in live-action default is enabled",
        )
    return Gate(
        "safe-defaults",
        GateStatus.PASS,
        "checked-in environment, Compose, and CI defaults keep live actions disabled",
    )


def _backup_restore_gate(root: Path) -> Gate:
    policy = _text(root, "infra/backup/policy.yml") or ""
    scripts = "\n".join(
        _text(root, path) or ""
        for path in (
            "scripts/backup-postgres.ps1",
            "scripts/restore-postgres.ps1",
            "scripts/backup-minio.ps1",
            "scripts/restore-minio.ps1",
        )
    )
    docs = (_text(root, "docs/operator/backup-restore.md") or "") + (
        _text(root, "docs/operator/migration-rehearsal.md") or ""
    )
    required = (
        "sha256",
        "pg_restore",
        "object_lock_required",
        "requires_isolated_target",
        "static readiness",
        "live qualification",
    )
    if any(
        value.lower() not in (policy + scripts + docs).lower() for value in required
    ):
        return Gate(
            "backup-restore",
            GateStatus.BLOCK,
            "backup, checksum, isolated-restore, or qualification guidance is incomplete",
        )
    return Gate(
        "backup-restore",
        GateStatus.PASS,
        "PostgreSQL/MinIO checksum and isolated restore controls are documented",
    )


def _health_observability_gate(root: Path) -> Gate:
    compose = _text(root, "infra/docker-compose.yml") or ""
    api = _text(root, "backend/api/main.py") or ""
    alerts = _text(root, "infra/observability/alerts.yml") or ""
    dashboard = (
        _text(root, "infra/observability/grafana/dashboards/operations.json") or ""
    )
    required = (
        "healthcheck",
        "/health/ready",
        "/health/live",
        "reclaim_backup_verification_total",
        "runbook_url",
        "reclaim_recovery_events_total",
    )
    if any(value not in compose + api + alerts + dashboard for value in required):
        return Gate(
            "health-observability",
            GateStatus.BLOCK,
            "application health or operational observability coverage is incomplete",
        )
    return Gate(
        "health-observability",
        GateStatus.PASS,
        "health endpoints, alert runbooks, and operational dashboards are configured",
    )


def _rollback_gate(root: Path) -> Gate:
    docs = "\n".join(
        _text(root, path) or ""
        for path in (
            "docs/operator/migration-rehearsal.md",
            "docs/operator/backup-restore.md",
            "docs/operator/deployment.md",
        )
    ).lower()
    required = (
        "rollback",
        "isolated restore",
        "never overwrites",
        "do not retry",
        "rto",
        "rpo",
    )
    if any(value not in docs for value in required):
        return Gate(
            "rollback-guidance",
            GateStatus.BLOCK,
            "rollback and uncertain-result guidance is incomplete",
        )
    return Gate(
        "rollback-guidance",
        GateStatus.PASS,
        "rollback uses isolated verified restore and preserves uncertain side effects",
    )


def _temporal_and_live_gate(root: Path) -> tuple[Gate, Gate]:
    tasks = _text(root, "specs/001-incident-intake-containment/tasks.md") or ""
    migration_doc = (_text(root, "docs/operator/migration-rehearsal.md") or "").lower()
    compose = (_text(root, "infra/docker-compose.yml") or "").lower()
    checklist = (
        "empty run inventory",
        "parity",
        "recovery",
        "fresh-volume",
        "do not remove",
    )
    if (
        any(value not in migration_doc for value in checklist)
        or "temporal" not in compose
    ):
        temporal = Gate(
            "temporal-drain",
            GateStatus.BLOCK,
            "Temporal drain/removal gate is not fail-closed or its compatibility artifacts are missing",
        )
    elif re.search(r"^- \[ \] T154\b", tasks, re.MULTILINE):
        temporal = Gate(
            "temporal-drain",
            GateStatus.OPEN,
            "T154 remains open pending empty inventory, parity, recovery, and fresh-volume evidence",
        )
    else:
        temporal = Gate(
            "temporal-drain",
            GateStatus.BLOCK,
            "T154 is not explicitly open; removal must remain gated",
        )
    if re.search(r"^- \[ \] T153\b", tasks, re.MULTILINE):
        live = Gate(
            "live-qualification",
            GateStatus.OPEN,
            "T153 live fresh-volume, recovery, and browser qualification remains unresolved",
        )
    else:
        live = Gate(
            "live-qualification",
            GateStatus.PASS,
            "T153 is marked complete in the task ledger",
        )
    return live, temporal


def run_preflight(
    root: Path,
    *,
    release_metadata: Path | None = None,
    production_env: Path | None = None,
) -> PreflightReport:
    """Run all repository-owned release gates without external side effects."""

    live, temporal = _temporal_and_live_gate(root)
    gates = (
        _required_files_gate(root),
        _release_metadata_gate(root, release_metadata),
        _pinned_versions_gate(root),
        _production_profile_gate(root),
        _production_inputs_gate(production_env),
        _safe_defaults_gate(root),
        _backup_restore_gate(root),
        _health_observability_gate(root),
        _rollback_gate(root),
        live,
        temporal,
    )
    return PreflightReport(gates)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--release-metadata", type=Path)
    parser.add_argument("--production-env", type=Path)
    args = parser.parse_args()
    report = run_preflight(
        args.root.resolve(),
        release_metadata=args.release_metadata.resolve()
        if args.release_metadata
        else None,
        production_env=args.production_env.resolve() if args.production_env else None,
    )
    for line in report.render():
        print(line)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
