"""T110 operator workflow acceptance boundary.

The browser-visible route and typed read-model/API seams are owned by T122-T124.
This source-level acceptance contract stays importable until the frontend and
mode-selection implementation exist; it never edits underlying records.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
UI_FILES = (
    REPOSITORY_ROOT / "frontend" / "src" / "app" / "cases" / "[caseId]" / "page.tsx",
    REPOSITORY_ROOT / "frontend" / "src" / "components" / "case" / "CaseTimeline.tsx",
    REPOSITORY_ROOT
    / "frontend"
    / "src"
    / "components"
    / "case"
    / "ExposureSummary.tsx",
    REPOSITORY_ROOT
    / "frontend"
    / "src"
    / "components"
    / "case"
    / "ActionDecisionPanel.tsx",
    REPOSITORY_ROOT / "frontend" / "src" / "components" / "case" / "ApprovalPanel.tsx",
    REPOSITORY_ROOT
    / "frontend"
    / "src"
    / "components"
    / "case"
    / "EscalationPanel.tsx",
    REPOSITORY_ROOT / "frontend" / "src" / "components" / "replay" / "ReplayPanel.tsx",
    REPOSITORY_ROOT / "frontend" / "src" / "components" / "audit" / "AuditTrace.tsx",
    REPOSITORY_ROOT / "frontend" / "src" / "components" / "replay" / "ModeBadge.tsx",
    REPOSITORY_ROOT / "frontend" / "src" / "lib" / "api.ts",
    REPOSITORY_ROOT / "backend" / "replay" / "mode_selection.py",
    REPOSITORY_ROOT / "backend" / "api" / "demo.py",
)
REQUIRED_REVIEW_TERMS = (
    "incident",
    "legitimate",
    "malicious",
    "remaining exposure",
    "containment",
    "next human decision",
    "audit",
    "approval",
    "escalation",
    "replay",
)


@pytest.mark.xfail(
    strict=True,
    reason="T110 is expected-red until T122/T123/T124 implement the operator workflow",
)
def test_operator_workflow_exposes_review_trace_without_record_mutation() -> None:
    missing_files = [
        str(path.relative_to(REPOSITORY_ROOT)) for path in UI_FILES if not path.exists()
    ]
    assert not missing_files, f"missing operator workflow seams: {missing_files}"

    source = "\n".join(path.read_text(encoding="utf-8") for path in UI_FILES).lower()
    missing_terms = [term for term in REQUIRED_REVIEW_TERMS if term not in source]
    assert not missing_terms, f"missing reviewer-visible fields: {missing_terms}"
    assert "replay" in source
    assert "live" in source
    assert "audit" in source
    assert "approval" in source
    assert "escalat" in source
    assert "delete" not in source
    assert "update" not in source
    assert "insert" not in source
