@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI BI V2 Launcher

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "API_PORT=8010"
set "WEB_PORT=5174"
set "WEB_ALREADY_RUNNING=0"

:find_web_port
netstat -ano | findstr /R /C:":!WEB_PORT! .*LISTENING" >nul
if errorlevel 1 goto :web_port_ready
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://localhost:!WEB_PORT!/' -TimeoutSec 2; if ($r.Content -match 'Insight Studio.+AI BI V2') { exit 0 }; exit 1 } catch { exit 1 }"
if not errorlevel 1 (
  set "WEB_ALREADY_RUNNING=1"
  goto :web_port_ready
)
echo [Info] Port !WEB_PORT! belongs to another application. Trying the next port...
set /a WEB_PORT+=1
if !WEB_PORT! GTR 5190 goto :web_port_failed
goto :find_web_port

:web_port_ready

echo.
echo   Insight Studio - AI BI V2.0
echo   API:  http://127.0.0.1:%API_PORT%
echo   Web:  http://127.0.0.1:%WEB_PORT%
echo.

where python >nul 2>nul
if errorlevel 1 goto :python_missing
where npm >nul 2>nul
if errorlevel 1 goto :npm_missing

if not exist "%FRONTEND%\node_modules\vite" (
  echo [Setup] Frontend dependencies are missing. Trying npm offline cache...
  pushd "%FRONTEND%"
  call npm.cmd install --offline --no-audit --no-fund
  set "NPM_RESULT=%ERRORLEVEL%"
  popd
  if not "%NPM_RESULT%"=="0" goto :offline_install_failed
)

netstat -ano | findstr /R /C:":%API_PORT% .*LISTENING" >nul
if errorlevel 1 (
  echo [Start] API service...
  start "AI BI V2 API" /min powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\run-api.ps1"
) else (
  echo [Info] Port %API_PORT% is already in use. API launch skipped.
)

if "%WEB_ALREADY_RUNNING%"=="0" (
  echo [Start] Web workbench...
  start "AI BI V2 Web" /min powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\run-web.ps1" -Port %WEB_PORT%
) else (
  echo [Info] AI BI V2 Web is already running on port %WEB_PORT%.
)

echo [Wait] Checking API and Web readiness...
set /a READY_TRIES=0
:wait_ready
set /a READY_TRIES+=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $api = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:%API_PORT%/api/v1/health' -TimeoutSec 2; $web = Invoke-WebRequest -UseBasicParsing 'http://localhost:%WEB_PORT%/' -TimeoutSec 2; if ($api.StatusCode -eq 200 -and $web.StatusCode -eq 200 -and $web.Content -match 'Insight Studio.+AI BI V2') { exit 0 }; exit 1 } catch { exit 1 }"
if not errorlevel 1 goto :ready
if %READY_TRIES% GEQ 20 goto :readiness_failed
timeout /t 1 /nobreak >nul
goto :wait_ready

:ready
echo [Ready] API and Web are responding. Opening the browser...
start "" "http://localhost:%WEB_PORT%"
echo Started. API and Web log windows are minimized; close them to stop services.
timeout /t 3 /nobreak >nul
exit /b 0

:readiness_failed
echo [Error] Services did not become ready within 20 seconds.
echo Check the minimized "AI BI V2 API" and "AI BI V2 Web" windows for details.
echo API health: http://127.0.0.1:%API_PORT%/api/v1/health
pause
exit /b 1

:python_missing
echo [Error] Python was not found. Install or configure Python 3.10+ and retry.
pause
exit /b 1

:npm_missing
echo [Error] npm was not found. Install or configure Node.js 20+ and retry.
pause
exit /b 1

:offline_install_failed
echo [Error] Frontend dependencies are not present in the local npm cache.
echo Run npm install in the frontend directory, or allow downloads, then retry.
pause
exit /b 1

:web_port_failed
echo [Error] No available web port was found between 5174 and 5190.
pause
exit /b 1
