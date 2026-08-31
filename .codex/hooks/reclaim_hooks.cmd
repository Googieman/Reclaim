@echo off
setlocal

set "RECLAIM_HOOK_ROOT=%~dp0..\.."
for /f "delims=" %%G in ('git -C "%RECLAIM_HOOK_ROOT%" rev-parse --show-toplevel') do set "RECLAIM_HOOK_ROOT=%%G"

if exist "%RECLAIM_HOOK_ROOT%\.venv\Scripts\python.exe" (
    "%RECLAIM_HOOK_ROOT%\.venv\Scripts\python.exe" -X utf8 "%RECLAIM_HOOK_ROOT%\.codex\hooks\reclaim_hooks.py" %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python -X utf8 "%RECLAIM_HOOK_ROOT%\.codex\hooks\reclaim_hooks.py" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    py -3 -X utf8 "%RECLAIM_HOOK_ROOT%\.codex\hooks\reclaim_hooks.py" %*
    exit /b %ERRORLEVEL%
)

>&2 echo RECLAIM Codex hooks require Python 3; no hook action was taken.
exit /b 0
