@echo off
setlocal EnableExtensions

set "RECLAIM_HOOK_ROOT=%~dp0..\.."
for /f "delims=" %%G in ('git -C "%RECLAIM_HOOK_ROOT%" rev-parse --show-toplevel 2^>nul') do set "RECLAIM_HOOK_ROOT=%%G"

if exist "%RECLAIM_HOOK_ROOT%\.venv\Scripts\python.exe" goto run_venv

where python >nul 2>&1
if errorlevel 1 goto check_py
python -c "import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)" >nul 2>&1
if errorlevel 1 goto check_py
goto run_python

:check_py
where py >nul 2>&1
if errorlevel 1 goto no_python
py -3 -c "import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)" >nul 2>&1
if errorlevel 1 goto no_python
goto run_py

:run_venv
"%RECLAIM_HOOK_ROOT%\.venv\Scripts\python.exe" -X utf8 "%RECLAIM_HOOK_ROOT%\.codex\hooks\reclaim_hooks.py" %*
exit /b %ERRORLEVEL%

:run_python
python -X utf8 "%RECLAIM_HOOK_ROOT%\.codex\hooks\reclaim_hooks.py" %*
exit /b %ERRORLEVEL%

:run_py
py -3 -X utf8 "%RECLAIM_HOOK_ROOT%\.codex\hooks\reclaim_hooks.py" %*
exit /b %ERRORLEVEL%

:no_python
>&2 echo RECLAIM Codex hooks require Python 3; no hook action was taken.
if /I "%~1"=="--event" if /I "%~2"=="PreToolUse" exit /b 2
exit /b 0
