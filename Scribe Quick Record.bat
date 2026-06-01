@echo off
REM Scribe Quick Record - taskbar shortcut.
REM Runs `scribe rec` from the project's uv-managed .venv. %~dp0 is this file's
REM own folder (the project root), so it works regardless of PATH or cwd.

title Scribe Quick Record
cd /d "%~dp0"

if not exist ".venv\Scripts\scribe.exe" (
    echo ERROR: Scribe is not installed. Run "uv sync" in "%~dp0" first.
    pause
    exit /b 1
)

".venv\Scripts\scribe.exe" rec

echo.
pause
