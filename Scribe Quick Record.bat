@echo off
REM Scribe Quick Record - Taskbar Shortcut
REM Double-click to start recording with auto-transcription

title Scribe Quick Record
color 0A

echo.
echo ========================================
echo   SCRIBE QUICK RECORD
echo ========================================
echo.

REM Run scribe rec command
scribe rec

echo.
echo Recording and transcription complete!
echo.
pause
