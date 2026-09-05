"""Source-level browser contract for the fresh-agent operator panel."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UI_FILES = (
    ROOT / "frontend" / "src" / "components" / "agent" / "FreshAgentPanel.tsx",
    ROOT / "frontend" / "src" / "components" / "agent" / "AgentRunBadge.tsx",
    ROOT / "frontend" / "src" / "components" / "case" / "FreshAgentPanel.tsx",
    ROOT / "frontend" / "src" / "components" / "replay" / "ReplayPanel.tsx",
    ROOT / "frontend" / "src" / "app" / "cases" / "[caseId]" / "page.tsx",
)


def test_operator_panel_keeps_fresh_replay_and_actions_separate() -> None:
    assert all(path.exists() for path in UI_FILES)
    source = "\n".join(path.read_text(encoding="utf-8") for path in UI_FILES).lower()

    assert "fresh agent analysis" in source
    assert "runfreshagent" in source
    assert "replay" in source
    assert "remote side effects" in source
    assert "approval" in source
    assert "action_environment" in source
    assert "executeaction" not in source
