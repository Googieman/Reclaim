"""Operator provisioning validation and redaction checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "provision_secrets", ROOT / "scripts" / "provision-secrets.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def populated_document() -> dict[str, object]:
    return {
        "template_only": False,
        "environment": "final",
        "secrets": [
            {
                "id": "api.evidence",
                "vault_path": "secret/data/reclaim/final/tenants/tenant-a/api/evidence",
                "values": {"access_key_id": "real-but-test-only"},
            }
        ],
    }


def test_provisioning_rejects_template_and_invalid_sentinel_values() -> None:
    with pytest.raises(MODULE.ProvisioningError, match="template_only"):
        MODULE.validate_document(
            {"template_only": True, "secrets": []}, allowed_paths={}
        )
    document = populated_document()
    document["secrets"] = [
        {
            "id": "api.evidence",
            "vault_path": "secret/data/reclaim/final/tenants/tenant-a/api/evidence",
            "values": {"access_key_id": "__REQUIRED_ACCESS_KEY__"},
        }
    ]
    with pytest.raises(MODULE.ProvisioningError, match="placeholder"):
        MODULE.validate_document(
            document,
            allowed_paths={"api.evidence": document["secrets"][0]["vault_path"]},
        )


def test_provisioning_rejects_path_override_and_dry_run_is_value_free(
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = populated_document()
    with pytest.raises(MODULE.ProvisioningError, match="Vault path"):
        MODULE.validate_document(
            document,
            allowed_paths={"api.evidence": "secret/data/other/path"},
        )
    result = MODULE.validate_document(
        document,
        allowed_paths={
            "api.evidence": "secret/data/reclaim/final/tenants/tenant-a/api/evidence"
        },
    )
    MODULE.print_dry_run(result)
    output = capsys.readouterr().out
    assert "real-but-test-only" not in output
    assert "api.evidence" in output
