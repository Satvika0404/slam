@echo off
rem Start the Ghost Data Console. Same as run_console.ps1, without needing a PowerShell policy change.
rem Options: -Port 9000   -Refresh   -NoBrowser   -Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_console.ps1" %*
