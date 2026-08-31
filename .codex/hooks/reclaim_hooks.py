"""Small, deterministic Codex development hooks for RECLAIM.

These hooks are advisory development guardrails. They are not an application
authorization boundary, a correctness authority, or a replacement for CI.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


TASKS_PATH = Path("specs/001-incident-intake-containment/tasks.md")
PROJECT_STATUS_PATH = Path("PROJECT_STATUS.md")
MAX_CONTEXT_LINES = 4
MAX_CONTEXT_LINE_LENGTH = 240
MAX_DISPLAY_PATHS = 8


def _read_payload() -> tuple[dict[str, Any], str | None]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}, None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON on hook stdin: {exc.msg}"
    if not isinstance(payload, dict):
        return {}, "hook stdin must contain a JSON object"
    return payload, None


def _git_root(cwd: str | None) -> Path | None:
    base = Path(cwd or os.getcwd())
    try:
        result = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    root_text = result.stdout.strip()
    return Path(root_text) if root_text else None


def _run_git(root: Path, args: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = result.stdout.strip() or result.stderr.strip()
    return result.returncode == 0, output


def _relative_path(value: str, root: Path) -> str:
    raw = str(value).strip().strip('"')
    text = raw.replace("\\", "/")
    if text.startswith("./"):
        text = text[2:]
    try:
        candidate_path = Path(raw)
        if not candidate_path.is_absolute():
            candidate_path = root / candidate_path
        candidate = candidate_path.resolve()
        text = candidate.relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        pass
    return text.strip("/")


def _status_entries(root: Path) -> list[tuple[str, str]]:
    ok, output = _run_git(root, ["status", "--short", "--untracked-files=all"])
    if not ok:
        return []
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        if len(line) < 3:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        entries.append((code, _relative_path(path, root)))
    return entries


def _changed_paths(root: Path) -> list[str]:
    paths = {path for _, path in _status_entries(root) if path}
    for args in (
        ["diff", "--name-only"],
        ["diff", "--cached", "--name-only"],
    ):
        ok, output = _run_git(root, args)
        if ok:
            paths.update(
                _relative_path(line, root)
                for line in output.splitlines()
                if line.strip()
            )
    return sorted(path for path in paths if path)


def _branch_and_head(root: Path) -> tuple[str, str]:
    _, branch = _run_git(root, ["branch", "--show-current"])
    _, head = _run_git(root, ["rev-parse", "--short", "HEAD"])
    return branch or "detached/unknown", head or "unknown"


def _matching_lines(
    path: Path, patterns: tuple[str, ...], limit: int = MAX_CONTEXT_LINES
) -> list[str]:
    if not path.is_file():
        return []
    matches: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                clean = line.strip()
                if clean and any(
                    re.search(pattern, clean, re.IGNORECASE) for pattern in patterns
                ):
                    matches.append(clean[:MAX_CONTEXT_LINE_LENGTH])
                    if len(matches) >= limit:
                        break
    except OSError:
        return []
    return matches


def _audit_paths(paths: list[str]) -> list[str]:
    return [
        path
        for path in paths
        if path.casefold() == "security-audits"
        or path.casefold().startswith("security-audits/")
    ]


def _display_paths(paths: list[str]) -> str:
    if not paths:
        return "none"
    shown = paths[:MAX_DISPLAY_PATHS]
    suffix = f"; +{len(paths) - len(shown)} more" if len(paths) > len(shown) else ""
    return ", ".join(shown) + suffix


def _session_context(root: Path) -> str:
    branch, head = _branch_and_head(root)
    status_entries = _status_entries(root)
    changed = [path for _, path in status_entries]
    audits = _audit_paths(changed)
    if not changed:
        working_tree = "clean"
    elif set(audits) == set(changed):
        working_tree = "security-audits/ is untracked (intentional baseline)"
    else:
        working_tree = f"changed paths: {_display_paths(changed)}"

    d3_lines = _matching_lines(
        root / PROJECT_STATUS_PATH,
        (r"\bD3\b.*(?:contract|approved|runtime|mapping)",),
        2,
    )
    t059_lines = _matching_lines(
        root / PROJECT_STATUS_PATH,
        (r"T059.*(?:blocked|held|started)",),
        2,
    )
    task_lines = _matching_lines(root / TASKS_PATH, (r"T059",), 1)
    d3_observation = " | ".join(d3_lines)
    t059_observation = " | ".join(t059_lines + task_lines)
    if not d3_observation:
        d3_observation = "not observed in the concise PROJECT_STATUS scan"
    if not t059_observation:
        t059_observation = "not observed in the concise PROJECT_STATUS/tasks scan"

    return "\n".join(
        [
            "RECLAIM development context (read-only observation)",
            f"Repository: {root} | branch: {branch} | HEAD: {head}",
            f"Working tree: {working_tree}",
            f"AGENTS.md: {'present' if (root / 'AGENTS.md').is_file() else 'absent'}",
            f"D3 gate observation: {d3_observation}",
            f"T059 gate observation: {t059_observation}",
            "Current guardrails: T059 is blocked; the D3 contract is approved but D3 runtime implementation is not started.",
            "Use specs/.../tasks.md and PROJECT_STATUS.md as authoritative progress; do not infer completion from chat history.",
            "security-audits/ is intentionally untracked and must be preserved.",
        ]
    )


def _command_segments(command: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.split(r"&&|\|\||[;&|\n]", command)
        if segment.strip()
    ]


def _has_force_flag(arguments: str) -> bool:
    if re.search(
        r"(?:^|\s)(?:-n[^\s;&|]*|--dry-run)(?:\s|$)", arguments, re.IGNORECASE
    ):
        return False
    return bool(
        re.search(r"(?:^|\s)--force(?:\s|$)", arguments, re.IGNORECASE)
        or re.search(r"(?:^|\s)-[^\s;&|]*f[^\s;&|]*(?:\s|$)", arguments, re.IGNORECASE)
    )


def _is_recursive_delete(segment: str) -> bool:
    return bool(
        re.search(
            r"(?:^|\s)(?:-r|-R|--recursive|-recurse|/s)(?:\s|$)", segment, re.IGNORECASE
        )
        or re.search(r"(?:^|\s)-[^\s;&|]*r[^\s;&|]*(?:\s|$)", segment, re.IGNORECASE)
    )


def _mentions_root_target(segment: str, root: Path) -> bool:
    normalized = segment.replace("/", "\\").casefold()
    root_text = str(root).replace("/", "\\").rstrip("\\").casefold()
    if re.search(r"(?:^|[\s\"'])\.(?:\\)?(?:[\s\"']|$)", normalized):
        return True
    if re.search(
        r"(?:^|[\s\"'])(?:%cd%|%[a-z0-9_]*root%|\$pwd(?:\.path)?|\$env:cd|\$env:[a-z0-9_]*root|\$[a-z0-9_]*root)(?:[\\/.)\s\"']|$)",
        normalized,
    ) or re.search(r"(?:get-location|(?<![\w-])pwd(?![\w-]))", normalized):
        return True
    if "git rev-parse --show-toplevel" in normalized:
        return True
    return bool(
        root_text
        and re.search(
            rf"(?:^|[\s\"']){re.escape(root_text)}(?:[\s\"']|$)",
            normalized,
        )
    )


def _mentions_unrelated_data(segment: str, root: Path) -> bool:
    lower = segment.replace("/", "\\").casefold()
    if re.search(r"(?:~|\$home|\$env:userprofile|%userprofile%)(?:[\\\s\"']|$)", lower):
        return True
    if re.search(
        r"[\\/]users[\\/][^\\/\s\"']+[\\/](?:documents|desktop|downloads|appdata|\.ssh|\.aws|\.azure)(?:[\\/\s\"']|$)",
        lower,
    ):
        return True

    root_text = str(root).replace("/", "\\").rstrip("\\").casefold()
    absolute_paths = re.findall(
        r"[a-z]:[\\/][^\s;&|\"']+|(?:^|\s)(/[a-z][^\s;&|\"']*)", lower
    )
    for candidate in absolute_paths:
        candidate = candidate.lstrip().rstrip(",)")
        if candidate.startswith(("/home/", "/users/", "/root/")):
            return True
        try:
            candidate_text = os.path.normcase(os.path.abspath(candidate))
            root_absolute = os.path.normcase(os.path.abspath(str(root)))
        except OSError:
            candidate_text = candidate
            root_absolute = root_text
        if root_absolute and (
            candidate_text == root_absolute
            or candidate_text.startswith(root_absolute + os.sep)
        ):
            continue
        if candidate.startswith("c:\\windows\\"):
            return True
        if candidate.startswith(("c:\\users\\", "\\\\")):
            return True
    return False


def _delete_command_reason(segment: str, root: Path) -> str | None:
    if not re.search(
        r"\b(?:rm|remove-item|ri|rmdir|rd|del|erase|shred|unlink)\b",
        segment,
        re.IGNORECASE,
    ):
        return None
    lower = segment.casefold()
    if re.search(r"(?<![\w-])\.git(?:[\\/\s\"']|$)", lower):
        return "blocked deletion of .git"
    if "security-audits" in lower or "security_audits" in lower:
        return "blocked destructive command targeting security-audits/"
    recursive = _is_recursive_delete(segment)
    if recursive and _mentions_root_target(segment, root):
        return "blocked recursive deletion of the repository root"
    if recursive and re.search(r"(?:^|\s)(?:\*|\.\\\*|\./\*)(?:\s|$)", segment):
        return "blocked broad recursive deletion from the current directory"
    if _mentions_unrelated_data(segment, root):
        return "blocked destructive command targeting unrelated developer data"
    if re.search(r"remove-item.*(?:get-childitem|gci|dir|\|).*?-recurse", lower):
        return "blocked broad PowerShell recursive deletion"
    return None


def _docker_reason(segment: str) -> str | None:
    lower = segment.casefold()
    if not re.search(r"\bdocker\b", lower):
        return None
    if re.search(
        r"\bdocker\s+(?:system|volume|image|container|network)\s+prune\b", lower
    ):
        if "--filter" not in lower or "label=reclaim" not in lower:
            return "blocked broad Docker prune; use an explicitly labeled RECLAIM test scope"
    if re.search(
        r"\bdocker\s+(?:volume\s+rm|image\s+(?:rm|rmi)|rmi|rm|container\s+rm)\b",
        lower,
    ) and re.search(
        r"\bdocker\s+(?:volume\s+ls|image\s+ls|images|container\s+ls|ps)\b[^;&|]*(?:-q\b|-[^\s;&|]*q[^\s;&|]*)",
        lower,
    ):
        return (
            "blocked indiscriminate Docker deletion driven by an all-resources listing"
        )
    return None


def _git_subcommand(segment: str, subcommand: str) -> re.Match[str] | None:
    token = r"(?:\"[^\"]+\"|'[^']+'|[^\s;&|]+)"
    return re.search(
        rf"\bgit(?:\s+-[^\s;&|]+(?:\s+{token})?)*\s+{subcommand}\b",
        segment,
        re.IGNORECASE,
    )


def _shell_reason(command: str, root: Path) -> str | None:
    for segment in _command_segments(command):
        lower = segment.casefold()
        reset_match = _git_subcommand(segment, "reset")
        if reset_match and re.search(
            r"(?:^|\s)--hard(?:\s|$)",
            segment[reset_match.end() :],
            re.IGNORECASE,
        ):
            return "blocked git reset --hard"

        clean_match = _git_subcommand(segment, "clean")
        clean_args = segment[clean_match.end() :] if clean_match else ""
        if clean_match and _has_force_flag(clean_args):
            if "security-audits" in lower or "security_audits" in lower:
                return "blocked git clean targeting security-audits/"
            return "blocked forced git clean; use a reviewed, scoped cleanup"

        checkout_match = _git_subcommand(segment, "checkout")
        if checkout_match and re.search(
            r"--\s+\.\s*$", segment[checkout_match.end() :]
        ):
            return "blocked git checkout -- ."
        restore_match = _git_subcommand(segment, "restore")
        if restore_match and re.search(
            r"(?:--\s+)?\.\s*$", segment[restore_match.end() :]
        ):
            return "blocked broad git restore of the working tree"
        rm_match = _git_subcommand(segment, "rm")
        if rm_match:
            if "security-audits" in lower or "security_audits" in lower:
                return "blocked git rm targeting security-audits/"
            if re.search(r"(?:^|\s)(?:\.|\.\\|\./)(?:\s|$)", segment):
                return "blocked broad git rm of the repository"

        reason = _docker_reason(segment)
        if reason:
            return reason
        reason = _delete_command_reason(segment, root)
        if reason:
            return reason
    return None


def _patch_paths(command: str, root: Path) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    pattern = re.compile(
        r"^\*\*\*\s+(Update File|Add File|Delete File|Move to):\s*(.+?)\s*$"
    )
    for line in command.splitlines():
        match = pattern.match(line.strip())
        if match:
            paths.append((match.group(1), _relative_path(match.group(2), root)))
    return paths


def _patch_reason(command: str, root: Path) -> str | None:
    for operation, path in _patch_paths(command, root):
        lower = path.casefold()
        if lower == ".git" or lower.startswith(".git/"):
            return "blocked file patch targeting .git"
        if operation == "Delete File" and (
            lower == "security-audits" or lower.startswith("security-audits/")
        ):
            return "blocked patch deletion targeting security-audits/"
        if operation == "Delete File" and not path:
            return "blocked patch with an unresolved deletion target"
    return None


def _pretool_output(payload: dict[str, Any], root: Path) -> dict[str, Any] | None:
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        command = ""
    reason = None
    if tool_name == "Bash":
        reason = _shell_reason(command, root)
    elif tool_name in {"apply_patch", "Edit", "Write"}:
        reason = _patch_reason(command, root) if command else None
        target = tool_input.get("file_path") or tool_input.get("path")
        if isinstance(target, str):
            target_path = _relative_path(target, root).casefold()
            if target_path == ".git" or target_path.startswith(".git/"):
                reason = "blocked file operation targeting .git"
    if not reason:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"RECLAIM development guard: {reason}.",
        }
    }


def _sensitive_categories(paths: list[str]) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    for raw_path in paths:
        path = raw_path.replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        lower = path.casefold()
        name = lower.rsplit("/", 1)[-1]
        category = None
        if lower == ".specify/memory/constitution.md":
            category = "constitution"
        elif "/contracts/" in f"/{lower}/" or lower.startswith("contracts/"):
            category = "contracts"
        elif "/decisions/" in f"/{lower}/" or re.search(r"(^|/)adr[-_]", lower):
            category = "adrs"
        elif name == "tasks.md":
            category = "tasks"
        elif "/migrations/" in f"/{lower}/" or re.search(
            r"migration[^/]*\.(sql|py)$", lower
        ):
            category = "migrations"
        elif re.search(r"(^|/)(auth|tenant|rls)(/|_|-)", lower):
            category = "auth/tenant/RLS"
        elif "action-gateway" in lower or "action_gateway" in lower:
            category = "Action Gateway"
        elif lower == "security-audits" or lower.startswith("security-audits/"):
            category = "security-audits"
        if category:
            categories.setdefault(category, []).append(path)
    return categories


def _tool_touched_paths(payload: dict[str, Any], root: Path) -> list[str]:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    command = tool_input.get("command")
    if not isinstance(command, str):
        return []
    return [path for _, path in _patch_paths(command, root)]


def _posttool_output(
    payload: dict[str, Any],
    root: Path,
    changed_paths_override: list[str] | None = None,
) -> dict[str, Any]:
    changed = (
        changed_paths_override
        if changed_paths_override is not None
        else _changed_paths(root)
    )
    categories = _sensitive_categories(changed)
    audit_paths = categories.get("security-audits", [])
    touched = _tool_touched_paths(payload, root)
    tool_text = json.dumps(payload.get("tool_input", {}), ensure_ascii=False).casefold()
    audit_touched = (
        any("security-audits" in path.casefold() for path in touched)
        or "security-audits" in tool_text
    )
    if audit_paths and not audit_touched:
        categories.pop("security-audits", None)

    warnings: list[str] = []
    if (
        categories.get("constitution")
        or categories.get("contracts")
        or categories.get("adrs")
    ):
        warnings.append(
            "contract/constitution/ADR paths are changed; confirm explicit approval before treating them as accepted"
        )
    if categories.get("tasks"):
        warnings.append(
            "tasks.md changed; completion must come from observed validation, not task edits alone"
        )
    if categories.get("migrations"):
        warnings.append(
            "migration paths changed; run fresh-migration and non-owner RLS validation where applicable"
        )
    if categories.get("auth/tenant/RLS"):
        warnings.append(
            "auth/tenant/RLS code changed; recheck authorization and tenant-isolation coverage"
        )
    if categories.get("Action Gateway"):
        warnings.append(
            "Action Gateway code changed; recheck approval, idempotency, reconciliation, and verification boundaries"
        )
    if categories.get("security-audits"):
        warnings.append(
            "security-audits/ changed or was referenced; verify the change is intentional and preserve audit provenance"
        )
    if not warnings:
        return {}
    context = "RECLAIM PostToolUse review: " + "; ".join(warnings) + "."
    return {
        "systemMessage": context,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        },
    }


def _diff_check(root: Path) -> tuple[bool, str]:
    failures: list[str] = []
    for args in (["diff", "--check"], ["diff", "--cached", "--check"]):
        ok, output = _run_git(root, args)
        if not ok:
            failures.append(
                output[:300] if output else "git diff --check could not be determined"
            )
    return not failures, " | ".join(failures)


def _stop_output(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    changed = _changed_paths(root)
    categories = _sensitive_categories(changed)
    entries = _status_entries(root)
    audit_entries = [
        (code, path) for code, path in entries if path in _audit_paths(changed)
    ]
    tracked_audit = [path for code, path in audit_entries if code.strip() != "??"]
    if not tracked_audit:
        categories.pop("security-audits", None)
    clean_diff, diff_detail = _diff_check(root)

    issues: list[str] = []
    if not clean_diff:
        issues.append(f"git diff --check needs attention: {diff_detail}")
    if (
        categories.get("constitution")
        or categories.get("contracts")
        or categories.get("adrs")
    ):
        issues.append(
            "protected contract/constitution/ADR paths changed; verify explicit approval and scope"
        )

    reminders: list[str] = []
    if changed:
        reminders.append(f"observed changed paths: {_display_paths(changed)}")
        reminders.append(
            "test execution is not determinable from stable Stop hook input; verify appropriate tests before claiming completion"
        )
    else:
        reminders.append("observed clean working tree")
    reminders.append(f"git diff --check: {'pass' if clean_diff else 'needs attention'}")
    if PROJECT_STATUS_PATH.as_posix() in changed:
        reminders.append(
            "PROJECT_STATUS.md changed; reconcile it from observed artifacts and checks"
        )
    if any(path.endswith("/tasks.md") or path == "tasks.md" for path in changed):
        reminders.append(
            "tasks.md changed; confirm task state from validation evidence"
        )
    if tracked_audit:
        reminders.append(
            "security-audits/ has tracked changes; verify provenance and intent"
        )
    elif _audit_paths(changed):
        reminders.append(
            "security-audits/ remains intentionally untracked; no cleanup was attempted"
        )

    stop_hook_active = bool(payload.get("stop_hook_active"))
    if issues and not stop_hook_active:
        return {
            "decision": "block",
            "reason": "Before ending, verify: " + "; ".join(issues) + ".",
        }
    message = "RECLAIM handoff check: " + "; ".join(reminders) + "."
    if issues:
        message += " Stop-hook continuation was already active, so no further continuation was requested."
    return {"systemMessage": message}


def _error_output(event: str, detail: str) -> dict[str, Any]:
    message = f"RECLAIM {event} hook could not inspect its input safely: {detail}. The hook did not modify the repository."
    return {"systemMessage": message}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event",
        required=True,
        choices=("SessionStart", "PreToolUse", "PostToolUse", "Stop"),
    )
    args = parser.parse_args(argv)
    payload, parse_error = _read_payload()
    root = _git_root(payload.get("cwd"))
    if root is None:
        print(json.dumps(_error_output(args.event, "git root could not be resolved")))
        return 0
    if parse_error:
        print(json.dumps(_error_output(args.event, parse_error)))
        return 0

    if args.event == "SessionStart":
        output: dict[str, Any] = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": _session_context(root),
            }
        }
    elif args.event == "PreToolUse":
        output = _pretool_output(payload, root) or {}
    elif args.event == "PostToolUse":
        output = _posttool_output(payload, root)
    else:
        output = _stop_output(payload, root)
    if output:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
