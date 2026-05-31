@echo off
REM Potato Audit - native double-click launcher.
REM Runs the read-only audit and opens the HTML report. No install, no admin needed.
REM ExecutionPolicy Bypass is scoped to THIS invocation only - nothing is changed system-wide.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Potato-Audit.ps1" %*
echo.
pause
