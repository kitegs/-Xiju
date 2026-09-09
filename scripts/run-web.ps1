param([int]$Port = 5174)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $projectRoot 'frontend')

Write-Host ''
Write-Host "AI BI V2 Web is starting at http://localhost:$Port" -ForegroundColor Green
Write-Host 'Keep this window open while using Insight Studio.' -ForegroundColor DarkGray
Write-Host ''

try {
    & npm.cmd run dev -- --host localhost --port $Port --strictPort
} catch {
    Write-Host "Web failed to start: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ''
Read-Host 'The web process stopped. Press Enter to close this window'
