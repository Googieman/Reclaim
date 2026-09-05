"""Focused regressions ensuring the fresh slice cannot weaken FS-001 controls."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from app.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_fresh_route_is_disabled_in_the_default_app() -> None:
    response = TestClient(create_app(settings=Settings())).post(
        "/tenants/tenant-canonical-demo/cases/case-canonical-demo-001/agent-runs",
        json={},
    )
    assert response.status_code == 404


def test_fresh_runtime_has_no_import_path_to_execution_services() -> None:
    source = (
        (ROOT / "backend" / "agent" / "fresh_run.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "action_gateway" not in source
    assert "approval" not in source
    assert "subprocess" not in source
    assert "requests." not in source
