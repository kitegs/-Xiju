@echo off
setlocal
cd /d "%~dp0"
echo [Insight Studio] Starting local Superset professional workspace...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-superset.ps1"
if errorlevel 1 (
  echo [ERROR] Superset failed to start. Core V2 was not changed.
  pause
  exit /b 1
)
set AIBI_SUPERSET_URL=http://localhost:8088
call "%~dp0start.bat"
