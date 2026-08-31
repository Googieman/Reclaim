"""Stdlib self-tests for the RECLAIM Codex hook dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

import reclaim_hooks


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / ".codex" / "hooks.json"


class HookSelfTests(unittest.TestCase):
    def test_hook_config_uses_current_event_matcher_handler_shape(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIn("hooks", config)
        for event in ("SessionStart", "PreToolUse", "PostToolUse", "Stop"):
            groups = config["hooks"][event]
            self.assertIsInstance(groups, list)
            self.assertTrue(groups)
            self.assertIn("hooks", groups[0])
            handler = groups[0]["hooks"][0]
            self.assertEqual(handler["type"], "command")
            self.assertIn("command", handler)
            self.assertIn("commandWindows", handler)

    def test_session_context_is_concise_and_contains_gate_reminders(self) -> None:
        context = reclaim_hooks._session_context(ROOT)
        self.assertLess(len(context.splitlines()), 16)
        self.assertIn("T059", context)
        self.assertIn("D3", context)
        self.assertIn("security-audits/", context)
        self.assertIn("authoritative progress", context)

    def test_allowed_commands_are_not_denied(self) -> None:
        allowed = (
            "git status --short",
            "git diff --check",
            "pytest -q",
            "ruff check .codex/hooks",
            "docker compose -f infra/docker-compose.test.yml down",
            "docker volume rm reclaim-test-temp-123",
            "git clean -ndx",
            "git clean -nfd",
        )
        for command in allowed:
            with self.subTest(command=command):
                self.assertIsNone(reclaim_hooks._shell_reason(command, ROOT))

    def test_destructive_commands_are_denied_without_execution(self) -> None:
        blocked = (
            "git reset --hard HEAD",
            "git -C C:\\Users\\varug\\Reclaim reset --hard HEAD",
            "git clean -fdx",
            "git -C C:\\Users\\varug\\Reclaim clean -fdx",
            "git checkout -- .",
            "Remove-Item -Recurse -Force .git",
            "Remove-Item -Recurse -Force (Get-Location)",
            "Remove-Item -Recurse -Force security-audits",
            "docker system prune -af",
            "docker volume prune -f",
            "docker rm $(docker ps -aq)",
            "docker image rm $(docker image ls -aq)",
            'Remove-Item -Recurse -Force "$env:USERPROFILE\\Documents"',
        )
        for command in blocked:
            with self.subTest(command=command):
                reason = reclaim_hooks._shell_reason(command, ROOT)
                self.assertIsNotNone(reason)

    def test_pretool_denial_uses_current_permission_shape(self) -> None:
        output = reclaim_hooks._pretool_output(
            {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}},
            ROOT,
        )
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "git reset --hard", output["hookSpecificOutput"]["permissionDecisionReason"]
        )

    def test_apply_patch_security_audit_delete_is_denied(self) -> None:
        patch = "*** Begin Patch\n*** Delete File: security-audits/example.md\n*** End Patch"
        self.assertIn("security-audits", reclaim_hooks._patch_reason(patch, ROOT))

    def test_posttool_classifies_synthetic_sensitive_paths(self) -> None:
        synthetic_paths = [
            ".specify/memory/constitution.md",
            "specs/001-incident-intake-containment/contracts/intake.md",
            "specs/001-incident-intake-containment/decisions/ADR-004.md",
            "specs/001-incident-intake-containment/tasks.md",
            "backend/db/migrations/002.sql",
            "backend/auth/tenant_rls.py",
            "backend/action-gateway/service.py",
            "security-audits/new-report.md",
        ]
        categories = reclaim_hooks._sensitive_categories(synthetic_paths)
        self.assertEqual(
            set(categories),
            {
                "constitution",
                "contracts",
                "adrs",
                "tasks",
                "migrations",
                "auth/tenant/RLS",
                "Action Gateway",
                "security-audits",
            },
        )

        output = reclaim_hooks._posttool_output(
            {"tool_input": {"command": "git diff"}}, ROOT, synthetic_paths
        )
        self.assertIn("explicit approval", output["systemMessage"])
        self.assertIn("fresh-migration", output["systemMessage"])
        self.assertIn("Action Gateway", output["systemMessage"])

        audit_output = reclaim_hooks._posttool_output(
            {
                "tool_input": {
                    "command": "*** Update File: security-audits/new-report.md"
                }
            },
            ROOT,
            ["security-audits/new-report.md"],
        )
        self.assertIn("security-audits/", audit_output["systemMessage"])

    def test_stop_does_not_continue_again_when_already_active(self) -> None:
        output = reclaim_hooks._stop_output(
            {"cwd": str(ROOT), "stop_hook_active": True}, ROOT
        )
        self.assertIn("systemMessage", output)
        self.assertNotIn("decision", output)

    def test_cli_session_start_returns_json(self) -> None:
        process = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("reclaim_hooks.py")),
                "--event",
                "SessionStart",
            ],
            cwd=ROOT,
            input=json.dumps({"cwd": str(ROOT), "source": "startup"}),
            capture_output=True,
            text=True,
            check=True,
        )
        output = json.loads(process.stdout)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")


if __name__ == "__main__":
    unittest.main()
