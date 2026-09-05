#!/usr/bin/env python3
"""Validate and optionally provision private Vault KV values.

This command is an operator/deployment tool.  It never prints values; the
tracked examples are intentionally rejected as templates and placeholders.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProvisioningError(ValueError):
    """Raised when a private provisioning input fails closed."""


@dataclass(frozen=True, slots=True)
class ProvisionedSecret:
    secret_id: str
    vault_path: str
    values: dict[str, str]


@dataclass(frozen=True, slots=True)
class ProvisioningPlan:
    secrets: tuple[ProvisionedSecret, ...]


def validate_document(
    document: dict[str, Any], *, allowed_paths: dict[str, str]
) -> ProvisioningPlan:
    if document.get("template_only") is True:
        raise ProvisioningError("template_only input cannot be provisioned")
    records = document.get("secrets")
    if not isinstance(records, list) or not records:
        raise ProvisioningError("at least one secret is required")
    result: list[ProvisionedSecret] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ProvisioningError("secret record must be an object")
        secret_id = record.get("id")
        vault_path = record.get("vault_path")
        values = record.get("values")
        if not isinstance(secret_id, str) or secret_id in seen:
            raise ProvisioningError("secret ID is missing or duplicated")
        if allowed_paths.get(secret_id) != vault_path:
            raise ProvisioningError("Vault path is not allowed by the installed policy")
        if not isinstance(values, dict) or not values:
            raise ProvisioningError("secret values are required")
        normalized: dict[str, str] = {}
        for key, value in values.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, str)
                or not value.strip()
            ):
                raise ProvisioningError("secret values must be non-empty strings")
            if value.startswith("__REQUIRED_") or value.startswith("__OPTIONAL_"):
                raise ProvisioningError(
                    "placeholder secret value cannot be provisioned"
                )
            normalized[key] = value
        seen.add(secret_id)
        result.append(ProvisionedSecret(secret_id, vault_path, normalized))
    return ProvisioningPlan(tuple(result))


def print_dry_run(plan: ProvisioningPlan) -> None:
    for secret in plan.secrets:
        print(f"validated secret_id={secret.secret_id} vault_path={secret.vault_path}")


def apply_plan(plan: ProvisioningPlan, *, address: str, token: str) -> None:
    if not address.startswith("https://"):
        raise ProvisioningError("Vault address must use HTTPS")
    import hvac

    client = hvac.Client(url=address, token=token)
    for secret in plan.secrets:
        prefix, mount, *path = secret.vault_path.split("/")
        if prefix != "secret" or mount != "data" or not path:
            raise ProvisioningError("Vault path must use the secret/data KV v2 prefix")
        client.secrets.kv.v2.create_or_update_secret(
            mount_point=prefix,
            path="/".join(path),
            secret=secret.values,
        )
        print(f"provisioned secret_id={secret.secret_id}")


def _allowed_paths() -> dict[str, str]:
    policy_path = (
        Path(__file__).resolve().parents[1] / "secrets" / "access-policy.example.json"
    )
    document = json.loads(policy_path.read_text(encoding="utf-8"))
    return {item["id"]: item["vault_kv_v2_path"] for item in document["secrets"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision RECLAIM secrets to Vault")
    parser.add_argument("--input", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    document = json.loads(args.input.read_text(encoding="utf-8"))
    plan = validate_document(document, allowed_paths=_allowed_paths())
    if args.dry_run:
        print_dry_run(plan)
        return 0
    address = os.environ.get("VAULT_ADDR", "")
    token = os.environ.get("VAULT_TOKEN", "")
    if not address or not token:
        raise ProvisioningError("VAULT_ADDR and VAULT_TOKEN are required for --apply")
    apply_plan(plan, address=address, token=token)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(main())
