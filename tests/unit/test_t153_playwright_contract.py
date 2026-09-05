"""Contracts for the real-Compose T153 browser suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
CONFIG = FRONTEND / "playwright.t153.config.ts"
INBOX = FRONTEND / "src" / "components" / "cases" / "CaseInbox.live.browser.spec.ts"
DETAIL = FRONTEND / "src" / "app" / "cases" / "[caseId]" / "CaseDetail.live.browser.spec.ts"


def test_t153_playwright_config_is_real_environment_gated() -> None:
    source = CONFIG.read_text(encoding="utf-8")
    assert "RECLAIM_T153_WEB_BASE_URL" in source
    assert "webServer" not in source
    assert "Desktop Chrome" in source
    assert "Pixel 5" in source
    assert "workers: 1" in source
    assert "timeout: 180_000" in source
    assert "live.browser.spec.ts" in source
    assert "retain-on-failure" in source


@pytest.mark.parametrize("path", (INBOX, DETAIL))
def test_t153_browser_specs_have_no_route_mocks_or_replay_fixtures(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    assert "page.route" not in source
    assert "route.fulfill" not in source
    assert "mocked" not in source.lower()
    assert "fixture" not in source.lower()
    assert "page.goto" in source
    assert "RECLAIM_T153" in source


def test_t153_package_script_points_at_dedicated_config() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["test:browser:t153"] == (
        "playwright test -c playwright.t153.config.ts"
    )
