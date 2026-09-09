param([string]$Image = "apache/superset:GHA-dev-30899754997")
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envFile = Join-Path $root "data\superset.env"
$curatedEnv = Join-Path $root "data\curated.env"
$configFile = Join-Path $root "deployment\superset\superset_config.py"
$dataDir = Join-Path $root "data"
$initLog = Join-Path $root "data\superset-init.log"
$mountConfig = "${configFile}:/app/pythonpath/superset_config.py:ro"

docker image inspect $Image *> $null
if ($LASTEXITCODE -ne 0) { throw "Superset image is not available locally: $Image. No image was downloaded." }
docker image inspect mysql:8.0 *> $null
if ($LASTEXITCODE -ne 0) { throw "MySQL 8.0 image is not available locally. No image was downloaded." }

if (-not (Test-Path $envFile)) {
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $secretBytes = New-Object byte[] 48; $rng.GetBytes($secretBytes)
  $guestBytes = New-Object byte[] 48; $rng.GetBytes($guestBytes)
  $passwordBytes = New-Object byte[] 18; $rng.GetBytes($passwordBytes)
  $secret = [Convert]::ToBase64String($secretBytes)
  $guest = [Convert]::ToBase64String($guestBytes)
  $password = ([Convert]::ToBase64String($passwordBytes) -replace '[^A-Za-z0-9]','').Substring(0,18) + '!aA1'
  @(
    "SUPERSET_SECRET_KEY=$secret",
    "SUPERSET_GUEST_TOKEN_JWT_SECRET=$guest",
    "SUPERSET_ADMIN_USERNAME=admin",
    "SUPERSET_ADMIN_PASSWORD=$password"
  ) | Set-Content -LiteralPath $envFile -Encoding ascii
}

if (-not (Test-Path $curatedEnv)) {
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rootBytes = New-Object byte[] 24; $rng.GetBytes($rootBytes)
  $userBytes = New-Object byte[] 24; $rng.GetBytes($userBytes)
  $rootPassword = (([Convert]::ToBase64String($rootBytes) -replace '[^A-Za-z0-9]','') + 'Aa1').Substring(0,24)
  $userPassword = (([Convert]::ToBase64String($userBytes) -replace '[^A-Za-z0-9]','') + 'Aa1').Substring(0,24)
  @(
    "MYSQL_ROOT_PASSWORD=$rootPassword",
    "MYSQL_DATABASE=insight_curated",
    "MYSQL_USER=insight",
    "MYSQL_PASSWORD=$userPassword"
  ) | Set-Content -LiteralPath $curatedEnv -Encoding ascii
}

docker network inspect aibi-v2-net *> $null
if ($LASTEXITCODE -ne 0) { docker network create aibi-v2-net *> $null }
$mysqlExisting = docker ps -a --filter "name=^/aibi-v2-mysql$" --format "{{.Names}}"
if ($mysqlExisting -ne "aibi-v2-mysql") {
  docker run -d --name aibi-v2-mysql --restart unless-stopped --network aibi-v2-net -p 127.0.0.1:3307:3306 --env-file $curatedEnv -v aibi-v2-curated-mysql:/var/lib/mysql mysql:8.0 | Out-Null
} else {
  docker start aibi-v2-mysql *> $null
  $mysqlNetworks = docker inspect aibi-v2-mysql --format "{{json .NetworkSettings.Networks}}"
  if ($mysqlNetworks -notmatch "aibi-v2-net") { docker network connect aibi-v2-net aibi-v2-mysql }
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
  docker exec aibi-v2-mysql mysqladmin ping -h 127.0.0.1 --silent *> $null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 1
}
if ($LASTEXITCODE -ne 0) { throw "Curated MySQL database did not become ready." }

function Start-SupersetMcp {
  $mcpRunning = docker ps --filter "name=^/aibi-v2-superset-mcp$" --format "{{.Names}}"
  if ($mcpRunning -eq "aibi-v2-superset-mcp") { return }
  $mcpExisting = docker ps -a --filter "name=^/aibi-v2-superset-mcp$" --format "{{.Names}}"
  if ($mcpExisting -eq "aibi-v2-superset-mcp") { docker rm -f aibi-v2-superset-mcp *> $null }
  docker run -d --no-healthcheck --name aibi-v2-superset-mcp --restart unless-stopped --network aibi-v2-net -p 127.0.0.1:5008:5008 --env-file $envFile -e SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py -v aibi-v2-superset-home:/app/superset_home -v $mountConfig $Image superset mcp run --host 0.0.0.0 --port 5008 | Out-Null
}

$running = docker ps --filter "name=^/aibi-v2-superset$" --format "{{.Names}}"
if ($running -eq "aibi-v2-superset") {
  $supersetNetworks = docker inspect aibi-v2-superset --format "{{json .NetworkSettings.Networks}}"
  if ($supersetNetworks -notmatch "aibi-v2-net") { docker network connect aibi-v2-net aibi-v2-superset }
  Start-SupersetMcp
  Write-Output "Superset, MCP and curated MySQL are already running."; exit 0
}
$existing = docker ps -a --filter "name=^/aibi-v2-superset$" --format "{{.Names}}"
if ($existing -eq "aibi-v2-superset") { docker rm -f aibi-v2-superset *> $null }

$adminPassword = ((Get-Content -LiteralPath $envFile | Where-Object { $_ -like 'SUPERSET_ADMIN_PASSWORD=*' }) -split '=',2)[1]
$mountData = "${dataDir}:/app/insight_data:ro"
docker run --rm --env-file $envFile -e SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py -v aibi-v2-superset-home:/app/superset_home -v $mountConfig $Image superset db upgrade *> $initLog
if ($LASTEXITCODE -ne 0) { Get-Content $initLog -Tail 30; throw "Superset database migration failed" }
docker run --rm --env-file $envFile -e SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py -v aibi-v2-superset-home:/app/superset_home -v $mountConfig $Image superset fab create-admin --username admin --firstname Insight --lastname Owner --email admin@local.insight --password $adminPassword *> $null
docker run --rm --env-file $envFile -e SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py -v aibi-v2-superset-home:/app/superset_home -v $mountConfig $Image superset init *> $initLog
if ($LASTEXITCODE -ne 0) { Get-Content $initLog -Tail 30; throw "Superset initialization failed" }
docker run -d --name aibi-v2-superset --restart unless-stopped --network aibi-v2-net --env-file $envFile -e SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py -p 8088:8088 -v aibi-v2-superset-home:/app/superset_home -v $mountConfig -v $mountData $Image gunicorn --bind 0.0.0.0:8088 --workers 2 --timeout 120 "superset.app:create_app()" | Out-Null
Start-SupersetMcp
Write-Output "Superset started at http://localhost:8088; MCP started at http://localhost:5008/mcp. Credentials are stored locally in $envFile"
