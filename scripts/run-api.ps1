$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $projectRoot 'backend')
$supersetEnv = Join-Path $projectRoot 'data\superset.env'
$curatedEnv = Join-Path $projectRoot 'data\curated.env'
if (Test-Path $supersetEnv) {
    $values = @{}
    Get-Content -LiteralPath $supersetEnv | ForEach-Object { $parts = $_ -split '=', 2; if ($parts.Length -eq 2) { $values[$parts[0]] = $parts[1] } }
    $env:AIBI_SUPERSET_URL = 'http://127.0.0.1:8088'
    $env:AIBI_SUPERSET_USERNAME = $values['SUPERSET_ADMIN_USERNAME']
    $env:AIBI_SUPERSET_PASSWORD = $values['SUPERSET_ADMIN_PASSWORD']
}
if (Test-Path $curatedEnv) {
    $curatedValues = @{}
    Get-Content -LiteralPath $curatedEnv | ForEach-Object { $parts = $_ -split '=', 2; if ($parts.Length -eq 2) { $curatedValues[$parts[0]] = $parts[1] } }
    $curatedUser = $curatedValues['MYSQL_USER']
    $curatedPassword = $curatedValues['MYSQL_PASSWORD']
    $curatedDatabase = $curatedValues['MYSQL_DATABASE']
    $env:AIBI_CURATED_DATABASE_URL = "mysql+pymysql://${curatedUser}:${curatedPassword}@127.0.0.1:3307/${curatedDatabase}?charset=utf8mb4"
    $env:AIBI_SUPERSET_CURATED_DATABASE_URI = "mysql://${curatedUser}:${curatedPassword}@aibi-v2-mysql:3306/${curatedDatabase}?charset=utf8mb4"
}

Write-Host ''
Write-Host 'AI BI V2 API is starting at http://127.0.0.1:8010' -ForegroundColor Green
Write-Host 'Keep this window open while using Insight Studio.' -ForegroundColor DarkGray
Write-Host ''

try {
    # The launcher is for end users, so it intentionally avoids Uvicorn's development
    # reloader. The reloader can keep a stale child process on Windows after an update.
    & python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
} catch {
    Write-Host "API failed to start: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ''
Read-Host 'The API process stopped. Press Enter to close this window'
