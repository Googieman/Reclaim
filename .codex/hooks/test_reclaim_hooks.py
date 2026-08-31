"""Stdlib self-tests for the RECLAIM Codex hook dispatcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import reclaim_hooks


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / ".codex" / "hooks.json"
FIXTURES = Path(__file__).with_name("fixtures")
CMD = os.environ.get("COMSPEC", "cmd.exe")


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _windows_hook_command(event: str) -> str:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    handler = config["hooks"][event][0]["hooks"][0]
    return handler["commandWindows"]


def _run_windows_hook(
    event: str,
    payload: dict[str, object] | None = None,
    cwd: Path = ROOT,
    raw_input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    event_payload = dict(payload or {})
    event_payload["cwd"] = str(cwd)
    stdin = raw_input if raw_input is not None else json.dumps(event_payload)
    # Codex invokes the Windows command as cmd.exe /C "<command>". Keep the
    # outer wrapper here so embedded quotes would fail this test as they did in
    # the real runtime.
    command = _windows_hook_command(event)
    wrapped_command = f'cmd.exe /D /C "{command}"'
    return subprocess.run(
        f"{CMD} /D /C {wrapped_command}",
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _stdout_json(process: subprocess.CompletedProcess[str]) -> dict[str, object]:
    if process.stderr.strip():
        raise AssertionError(f"unexpected hook stderr: {process.stderr!r}")
    if not process.stdout.strip():
        raise AssertionError("hook did not emit the required JSON response")
    return json.loads(process.stdout)


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
            self.assertEqual(
                handler["commandWindows"],
                f"cmd.exe /D /C .codex\\hooks\\reclaim_hooks.cmd --event {event}",
            )
            self.assertNotIn('"', handler["commandWindows"])

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

    def test_windows_paths_and_file_uri_cwd_resolve(self) -> None:
        self.assertEqual(
            reclaim_hooks._git_root("file:///C:/Users/varug/Reclaim"), ROOT
        )
        self.assertEqual(reclaim_hooks._git_root(str(ROOT)), ROOT)

    def test_real_shape_session_start_uses_launcher(self) -> None:
        process = _run_windows_hook("SessionStart", _fixture("session-start.json"))
        self.assertEqual(process.returncode, 0, process.stderr)
        output = _stdout_json(process)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_real_shape_safe_powershell_pretool_uses_launcher(self) -> None:
        process = _run_windows_hook(
            "PreToolUse", _fixture("pre-tool-use-safe-powershell.json")
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "")

    def test_real_shape_dangerous_git_reset_pretool_denies(self) -> None:
        process = _run_windows_hook(
            "PreToolUse", _fixture("pre-tool-use-dangerous-git-reset.json")
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        output = _stdout_json(process)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "deny")
        self.assertIn("git reset --hard", specific["permissionDecisionReason"])

    def test_real_shape_safe_compose_pretool_allows(self) -> None:
        process = _run_windows_hook(
            "PreToolUse", _fixture("pre-tool-use-safe-compose.json")
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "")

    def test_real_shape_dangerous_docker_prune_pretool_denies(self) -> None:
        process = _run_windows_hook(
            "PreToolUse", _fixture("pre-tool-use-dangerous-docker-prune.json")
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        output = _stdout_json(process)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "Docker prune", output["hookSpecificOutput"]["permissionDecisionReason"]
        )

    def test_real_shape_normal_posttool_uses_launcher(self) -> None:
        process = _run_windows_hook(
            "PostToolUse", _fixture("post-tool-use-normal.json")
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "")

    def test_changed_contract_posttool_warns(self) -> None:
        output = reclaim_hooks._posttool_output(
            _fixture("post-tool-use-normal.json"),
            ROOT,
            ["specs/001-incident-intake-containment/contracts/intake.md"],
        )
        self.assertIn("explicit approval", output["systemMessage"])
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def test_real_shape_stop_uses_launcher(self) -> None:
        process = _run_windows_hook("Stop", _fixture("stop.json"))
        self.assertEqual(process.returncode, 0, process.stderr)
        output = _stdout_json(process)
        self.assertIn("systemMessage", output)

    def test_unknown_optional_fields_are_ignored(self) -> None:
        payload = _fixture("pre-tool-use-safe-powershell.json")
        payload["future_optional_field"] = {"nested": None}
        payload["tool_input"]["future_tool_field"] = None
        process = _run_windows_hook("PreToolUse", payload)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "")

    def test_unknown_safe_command_tool_is_allowed(self) -> None:
        payload = _fixture("pre-tool-use-safe-powershell.json")
        payload["tool_name"] = "FutureSafeCommandTool"
        payload["tool_input"] = {"command": "echo safe"}
        process = _run_windows_hook("PreToolUse", payload)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "")

    def test_missing_optional_or_nullable_fields_do_not_crash(self) -> None:
        payload = _fixture("post-tool-use-normal.json")
        payload.pop("transcript_path")
        payload["tool_response"] = None
        process = _run_windows_hook("PostToolUse", payload)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "")

    def test_malformed_json_is_advisory_for_non_pretool_events(self) -> None:
        for event in ("SessionStart", "PostToolUse", "Stop"):
            with self.subTest(event=event):
                process = _run_windows_hook(event, raw_input="{not-json")
                self.assertEqual(process.returncode, 0, process.stderr)
                output = _stdout_json(process)
                if event == "SessionStart":
                    self.assertEqual(
                        output["hookSpecificOutput"]["hookEventName"], "SessionStart"
                    )
                else:
                    self.assertIn("systemMessage", output)

    def test_malformed_pretool_payload_denies_closed(self) -> None:
        process = _run_windows_hook("PreToolUse", raw_input='{"tool_input":')
        self.assertEqual(process.returncode, 0, process.stderr)
        output = _stdout_json(process)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "deny")
        self.assertIn("not authorized", specific["permissionDecisionReason"])

    def test_launcher_prefers_venv_and_has_fallbacks(self) -> None:
        launcher = (ROOT / ".codex" / "hooks" / "reclaim_hooks.cmd").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            launcher.index("goto run_venv"), launcher.index("goto run_python")
        )
        self.assertLess(
            launcher.index("python -X utf8"), launcher.index("py -3 -X utf8")
        )
        self.assertIn("where python", launcher)
        self.assertIn("where py", launcher)
        self.assertIn('if /I "%~2"=="PreToolUse" exit /b 2', launcher)
        self.assertTrue((ROOT / ".venv" / "Scripts" / "python.exe").is_file())

    def test_launcher_works_from_nested_repository_directory(self) -> None:
        nested = ROOT / "specs" / "001-incident-intake-containment"
        payload = _fixture("session-start.json")
        payload["cwd"] = str(nested)
        process = subprocess.run(
            f'{CMD} /D /C call "{ROOT / ".codex" / "hooks" / "reclaim_hooks.cmd"}" --event SessionStart',
            cwd=nested,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        output = _stdout_json(process)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")


if __name__ == "__main__":
    unittest.main()
