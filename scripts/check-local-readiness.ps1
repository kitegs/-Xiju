param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$checks = @()
$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $Python -c "import sys, importlib.util; names=['fastapi','uvicorn','sqlalchemy','pymysql','aiosqlite','multipart','pandas','duckdb','openpyxl','httpx','cryptography','docx','matplotlib']; missing=[n for n in names if importlib.util.find_spec(n) is None]; print('Python:',sys.version.split()[0]); print('Missing backend modules:', ', '.join(missing) or 'none'); sys.exit(1 if missing or sys.version_info < (3,10) else 0)"
    $checks += [pscustomobject]@{ Check='Python and backend imports'; Ready=($LASTEXITCODE -eq 0) }
} else { $checks += [pscustomobject]@{ Check='Python on PATH'; Ready=$false } }
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$nodeReady = $false
if ($nodeCommand) { & node -e "console.log('Node:',process.version); process.exit(Number(process.versions.node.split('.')[0])>=20?0:1)"; $nodeReady = $LASTEXITCODE -eq 0 }
$checks += [pscustomobject]@{ Check='Node 20+'; Ready=$nodeReady }
$checks += [pscustomobject]@{ Check='npm on PATH'; Ready=([bool](Get-Command npm.cmd -ErrorAction SilentlyContinue)) }
foreach($module in @('vite','vue','echarts')) {
    $checks += [pscustomobject]@{ Check="Frontend $module"; Ready=(Test-Path -LiteralPath (Join-Path $projectRoot "frontend\node_modules\$module\package.json")) }
}
$checks | Format-Table -AutoSize
Write-Host 'Read-only check. No installation, server startup or model request was performed.'
Write-Host 'This verifies installed modules, not a clean-machine installation or all dependency version constraints.'
Write-Host 'If using -Python, activate that same Python environment before running start.bat.'
if ($checks | Where-Object { -not $_.Ready }) { exit 1 }
exit 0
