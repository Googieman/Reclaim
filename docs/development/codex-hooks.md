# RECLAIM Codex development hooks

RECLAIM keeps a small, project-local Codex harness in `.codex/hooks.json` and
`.codex/hooks/`. It is a development aid, not a correctness or security
authority.

## Hooks

- `SessionStart` reads the git root, branch/HEAD, concise status, `PROJECT_STATUS.md`,
  the current task/gate lines, `AGENTS.md`, and the intentional `security-audits/`
  status. It injects the D3/T059 gate reminder on startup, resume, clear, and
  compaction-supported starts.
- `PreToolUse` reviews shell commands and patch-style file edits. It denies only
  clearly destructive operations such as hard resets, forced broad cleans, root or
  `.git` deletion, broad Docker prunes, indiscriminate Docker resource deletion,
  destructive `security-audits/` targets, and destructive commands aimed at
  unrelated developer data. It allows normal inspection, tests, scoped Compose
  work, and ordinary edits.
- `PostToolUse` classifies observed changed paths and warns about contracts,
  constitution/ADR decisions, tasks, migrations, auth/tenant/RLS, Action Gateway,
  and security-audit changes. It does not run the full test suite or edit files.
- `Stop` reports status, `git diff --check`, changed-path governance reminders,
  task/status-file changes, and the intentional audit baseline. Test execution is
  reported as unknown when it cannot be established from stable hook input. It
  may request one focused continuation for a diff-check failure or protected-file
  change, and honors `stop_hook_active` to avoid loops.

## Trust and Windows

Use `/hooks` in Codex CLI/Desktop to inspect the exact project-local definitions,
review them, trust them, or disable an individual hook. New or changed
non-managed hooks do not run until trusted. Do not bypass that review casually.

The JSON uses the current event → matcher → handler format. Unix-like runs resolve
the script from `git rev-parse --show-toplevel`; Windows uses a quote-free
`commandWindows` delegation to the small `reclaim_hooks.cmd` launcher. The
launcher resolves the same git root and prefers a repository `.venv`, then a
validated `python`, then a validated `py -3`.
The hook logic uses Python standard-library code only and receives Codex's JSON
event on stdin. Codex's Windows runner wraps the configured value for `cmd.exe
/C`, so embedded quotes can prevent the command from starting. The configured
value therefore contains no quotes and delegates to `.codex\hooks\reclaim_hooks.cmd`.

Codex 0.151 event payloads include `session_id`, `transcript_path`, `cwd`,
`hook_event_name`, `model`, and `permission_mode`. Tool events also carry
`turn_id`, `tool_name`, `tool_input`, and `tool_use_id`; `PostToolUse` carries
`tool_response`; `SessionStart` adds `source`; and `Stop` adds
`stop_hook_active` and `last_assistant_message`. Nullable fields are accepted
as null, and unknown fields are ignored.

Responses are JSON on stdout only. `PreToolUse` emits the current
`hookSpecificOutput.permissionDecision` deny shape for a deliberate block and
otherwise emits no output. `SessionStart` and `PostToolUse` use their matching
`hookSpecificOutput` context shape; `Stop` emits a JSON `systemMessage` or its
documented continuation decision. Parsing, cwd, and context failures exit zero:
advisory events return concise diagnostic context, while a malformed or
uninspectable `PreToolUse` payload returns a deny response. Hook diagnostics
never write command output or tool responses to stdout.
If no Python interpreter is available, the launcher returns exit 2 for
`PreToolUse` and exit 0 for advisory events.

## Validation and temporary disablement

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -X utf8 .codex/hooks/test_reclaim_hooks.py
.\.venv\Scripts\python.exe -m json.tool .codex/hooks.json
```

The self-tests invoke each configured `commandWindows` handler through
`cmd.exe` from the repository root and a nested repository directory, using
synthetic payloads captured from the Codex 0.151 event schemas. They also cover
malformed JSON, nullable/missing fields, Windows paths, safe and dangerous
commands, and launcher interpreter order.

If no repository virtualenv is present, use an available `python` or `py -3`
command instead.

To temporarily disable hooks, use `/hooks` or set `[features].hooks = false` in
the applicable local Codex configuration. Restore the setting after diagnosis.

These hooks never replace PostgreSQL constraints/RLS, application authorization,
deterministic policy, tests, CI, service boundaries, or the isolated Action
Gateway. RECLAIM security and financial correctness never depend on hook behavior.
