<#
.SYNOPSIS
Starts a Windows-native local development environment.

.DESCRIPTION
Runs PostgreSQL, Redis, and Sandbox through Docker Compose. Gateway and
Frontend run as local reloadable processes, so application changes do not
require rebuilding Docker images. A lightweight Nginx container exposes them
through http://localhost, matching the full Docker development entrypoint.

.PARAMETER Detach
Starts the local Gateway and Frontend, then returns. Use -Stop later to end
only the processes created by this script.

.PARAMETER Stop
Stops only the Gateway and Frontend processes recorded by this script. Docker
infrastructure remains running for faster subsequent starts.

.PARAMETER BuildSandbox
Rebuilds the Sandbox image before starting it. Omit during normal UI/Gateway
development.

.PARAMETER WithPgAdmin
Also starts pgAdmin on http://localhost:5050.

.EXAMPLE
.\scripts\dev-local.ps1

.EXAMPLE
.\scripts\dev-local.ps1 -Detach

.EXAMPLE
.\scripts\dev-local.ps1 -Stop
#>
[CmdletBinding()]
param(
    [switch]$Detach,
    [switch]$Stop,
    [switch]$BuildSandbox,
    [switch]$WithPgAdmin,
    [ValidateRange(10, 180)]
    [int]$StartupTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot 'dev/docker-compose.yml'
$PythonExe = Join-Path $ProjectRoot '.ignore/codex-py311-venv/Scripts/python.exe'
$AlembicConfig = Join-Path $ProjectRoot 'apps/shared/alembic.ini'
$ClientDirectory = Join-Path $ProjectRoot 'apps/client'
$LocalProxyConfig = Join-Path $ProjectRoot 'dev/nginx.local-host.conf'
$LocalProxyContainerName = 'nodease-dev-local-proxy'
$RunDirectory = Join-Path $ProjectRoot '.codex-run-logs/dev-local'
$StateFile = Join-Path $RunDirectory 'processes.json'

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "'$Name' command was not found. Install it or add it to PATH."
    }
}

function Get-ListeningProcess {
    param([Parameter(Mandatory)][int]$Port)

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $listener) {
        return $null
    }

    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    return [PSCustomObject]@{
        Id = $listener.OwningProcess
        Name = if ($process) { $process.ProcessName } else { 'unknown' }
    }
}

function Assert-PortAvailable {
    param([Parameter(Mandatory)][int]$Port, [Parameter(Mandatory)][string]$ServiceName)

    $process = Get-ListeningProcess -Port $Port
    if ($process) {
        throw "$ServiceName cannot start because port $Port is already used by $($process.Name) (PID $($process.Id)). Stop that process or use the existing local environment."
    }
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastErrorMessage = 'no HTTP response received'
    do {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            $lastErrorMessage = $_.Exception.Message
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    throw "$ServiceName did not become available at $Uri within $TimeoutSeconds seconds. Last error: $lastErrorMessage"
}

function Wait-ForComposeCommand {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$ServiceName,
        [Parameter(Mandatory)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        & docker @Arguments *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    throw "$ServiceName did not become ready within $TimeoutSeconds seconds."
}

function Initialize-DatabaseVectorExtension {
    $vectorExtensionArguments = @(
        'compose', '-f', $ComposeFile, 'exec', '-T', 'postgres',
        'psql', '-U', 'admin', '-d', 'moduly_local', '-v', 'ON_ERROR_STOP=1',
        '-c', 'CREATE EXTENSION IF NOT EXISTS vector;'
    )

    Write-Host 'Ensuring pgvector extension...'
    & docker @vectorExtensionArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'pgvector extension initialization failed. Database migrations were not started.'
    }
}
function Invoke-DatabaseMigrations {
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $ProjectRoot
        Initialize-DatabaseVectorExtension
        Write-Host 'Applying database migrations...'
        & $PythonExe -m alembic -c $AlembicConfig upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw 'Database migrations failed. Gateway was not started.'
        }
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
}

function Get-RecordedState {
    if (-not (Test-Path -LiteralPath $StateFile)) {
        return $null
    }
    return Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
}

function Stop-RecordedProcess {
    param([Parameter(Mandatory)]$Record, [Parameter(Mandatory)][string]$ServiceName)

    $process = Get-Process -Id ([int]$Record.processId) -ErrorAction SilentlyContinue
    if (-not $process) {
        Write-Host "$ServiceName is already stopped."
        return
    }

    $actualStartedAt = $process.StartTime.ToUniversalTime().ToString('o')
    if ($actualStartedAt -ne $Record.startedAtUtc) {
        Write-Warning "Refusing to stop $ServiceName PID $($Record.processId): the PID now belongs to a different process."
        return
    }

    & taskkill.exe /PID $process.Id /T /F *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop $ServiceName process tree (PID $($process.Id))."
    }
    Write-Host "Stopped $ServiceName process tree (PID $($process.Id))."
}

function Stop-RecordedEnvironment {
    $state = Get-RecordedState
    if (-not $state) {
        Write-Host 'No dev-local Gateway or Frontend process record was found.'
        return
    }

    Stop-RecordedProcess -Record $state.gateway -ServiceName 'Gateway'
    Stop-RecordedProcess -Record $state.frontend -ServiceName 'Frontend'
    if ($state.PSObject.Properties.Name -contains 'proxyContainerName') {
        Stop-LocalProxy -ContainerName $state.proxyContainerName
    }
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    Write-Host 'Docker infrastructure was left running.'
}

function Get-LocalProxyLabel {
    param([Parameter(Mandatory)][string]$ContainerName)

    $containerId = & docker container ls --all --quiet --filter "name=^/$ContainerName$"
    if (-not $containerId) {
        return $null
    }
    $inspection = & docker container inspect ($containerId | Select-Object -First 1)
    $container = ($inspection | ConvertFrom-Json | Select-Object -First 1)
    if (-not $container.Config.Labels) {
        return $null
    }
    return $container.Config.Labels.'com.nodease.dev-local'
}

function Ensure-LocalProxy {
    if (-not (Test-Path -LiteralPath $LocalProxyConfig)) {
        throw "Local Nginx proxy configuration was not found: $LocalProxyConfig"
    }

    $existingLabel = Get-LocalProxyLabel -ContainerName $LocalProxyContainerName
    if ($existingLabel) {
        if ($existingLabel -ne 'true') {
            throw "Container '$LocalProxyContainerName' already exists but is not managed by dev-local. Rename or remove it before starting dev-local."
        }
        & docker start $LocalProxyContainerName *> $null
        if ($LASTEXITCODE -ne 0) {
            throw 'The existing local Nginx proxy could not be started. Check whether port 80 is already in use.'
        }
    } else {
        $mount = "type=bind,source=$LocalProxyConfig,target=/etc/nginx/conf.d/default.conf,readonly"
        & docker run --detach --rm --name $LocalProxyContainerName --label 'com.nodease.dev-local=true' --mount $mount -p '80:80' nginx:1.27-alpine *> $null
        if ($LASTEXITCODE -ne 0) {
            throw 'The local Nginx proxy could not start. Check Docker Desktop and whether port 80 is already in use.'
        }
    }

    Wait-ForHttp -Uri 'http://127.0.0.1/health' -ServiceName 'Local Nginx proxy' -TimeoutSeconds $StartupTimeoutSeconds
}

function Stop-LocalProxy {
    param([string]$ContainerName)

    if ([string]::IsNullOrWhiteSpace($ContainerName)) {
        return
    }
    if ((Get-LocalProxyLabel -ContainerName $ContainerName) -ne 'true') {
        return
    }
    & docker stop $ContainerName *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host 'Stopped local Nginx proxy.'
    }
}

function Save-RecordedState {
    param(
        [Parameter(Mandatory)]$GatewayProcess,
        [Parameter(Mandatory)]$FrontendProcess
    )

    $state = [PSCustomObject]@{
        gateway = [PSCustomObject]@{
            processId = $GatewayProcess.Id
            startedAtUtc = $GatewayProcess.StartTime.ToUniversalTime().ToString('o')
        }
        frontend = [PSCustomObject]@{
            processId = $FrontendProcess.Id
            startedAtUtc = $FrontendProcess.StartTime.ToUniversalTime().ToString('o')
        }
        proxyContainerName = $LocalProxyContainerName
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $StateFile
}

function Show-RunningEnvironment {
    Write-Host 'The dev-local environment is already running:'
    Write-Host '  App:      http://localhost'
    Write-Host '  Frontend: http://localhost:3000'
    Write-Host '  Gateway:  http://localhost:8000'
    Write-Host '  Swagger:  http://localhost:8000/docs'
    Write-Host '  Logs:     .codex-run-logs/dev-local'
    Write-Host 'Stop local Gateway and Frontend with .\scripts\dev-local.ps1 -Stop.'
}

if ($Stop) {
    Stop-RecordedEnvironment
    exit 0
}

Assert-Command -Name 'docker'
Assert-Command -Name 'npm.cmd'

if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "Compose file was not found: $ComposeFile"
}
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python 3.11 virtual environment was not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $LocalProxyConfig)) {
    throw "Local Nginx proxy configuration was not found: $LocalProxyConfig"
}
if (-not (Test-Path -LiteralPath (Join-Path $ClientDirectory 'node_modules/.bin/next.cmd'))) {
    throw "Frontend dependencies are missing. Restore apps/client/node_modules before starting dev-local."
}

& $PythonExe -c "import sys, fastapi, uvicorn; assert sys.version_info[:2] == (3, 11)"
if ($LASTEXITCODE -ne 0) {
    throw 'The local Gateway Python environment is not Python 3.11 with FastAPI and Uvicorn installed.'
}

$existingState = Get-RecordedState
if ($existingState) {
    $gateway = Get-Process -Id ([int]$existingState.gateway.processId) -ErrorAction SilentlyContinue
    $frontend = Get-Process -Id ([int]$existingState.frontend.processId) -ErrorAction SilentlyContinue
    if ($gateway -and $frontend) {
        Invoke-DatabaseMigrations
        Ensure-LocalProxy
        Save-RecordedState -GatewayProcess $gateway -FrontendProcess $frontend
        Show-RunningEnvironment
        exit 0
    }
    if ($gateway -or $frontend) {
        throw 'A partially running dev-local environment is recorded. Use .\scripts\dev-local.ps1 -Stop before starting another one.'
    }
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
}

Assert-PortAvailable -Port 8000 -ServiceName 'Gateway'
Assert-PortAvailable -Port 3000 -ServiceName 'Frontend'

$composeServices = @('postgres', 'redis', 'sandbox')
if ($WithPgAdmin) {
    $composeServices += 'pgadmin'
}
$composeArguments = @('compose', '-f', $ComposeFile, 'up', '-d')
if ($BuildSandbox) {
    $composeArguments += '--build'
}
$composeArguments += $composeServices

Write-Host 'Starting Docker infrastructure...'
& docker @composeArguments
if ($LASTEXITCODE -ne 0) {
    throw 'Docker infrastructure did not start. Check Docker Desktop and ports 5432, 6379, and 8194.'
}

$composePrefix = @('compose', '-f', $ComposeFile, 'exec', '-T')
Wait-ForComposeCommand -Arguments ($composePrefix + @('postgres', 'pg_isready', '-U', 'admin', '-d', 'moduly_local')) -ServiceName 'PostgreSQL' -TimeoutSeconds $StartupTimeoutSeconds
Invoke-DatabaseMigrations
Wait-ForComposeCommand -Arguments ($composePrefix + @('redis', 'redis-cli', 'ping')) -ServiceName 'Redis' -TimeoutSeconds $StartupTimeoutSeconds
Wait-ForHttp -Uri 'http://127.0.0.1:8194/health' -ServiceName 'Sandbox' -TimeoutSeconds $StartupTimeoutSeconds

New-Item -ItemType Directory -Path $RunDirectory -Force | Out-Null
$logRunId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$gatewayOut = Join-Path $RunDirectory "gateway-$logRunId.stdout.log"
$gatewayErr = Join-Path $RunDirectory "gateway-$logRunId.stderr.log"
$frontendOut = Join-Path $RunDirectory "frontend-$logRunId.stdout.log"
$frontendErr = Join-Path $RunDirectory "frontend-$logRunId.stderr.log"

$previousPythonPath = $env:PYTHONPATH
$previousWatchfilesPolling = $env:WATCHFILES_FORCE_POLLING
$previousWatchfilesIgnorePermissionDenied = $env:WATCHFILES_IGNORE_PERMISSION_DENIED
$previousPythonUtf8 = $env:PYTHONUTF8
$previousNodeEnv = $env:NODE_ENV
$previousNextPublicApiUrl = $env:NEXT_PUBLIC_API_URL
$previousApiUrl = $env:API_URL
$previousIntentCacheEnabled = $env:AGENT_BUILDER_INTENT_CACHE_ENABLED
$previousIntentCacheRedisUrl = $env:AGENT_BUILDER_INTENT_CACHE_REDIS_URL
$previousIntentCacheHmacKey = $env:AGENT_BUILDER_INTENT_CACHE_HMAC_KEY
$previousIntentCacheHmacKeyVersion = $env:AGENT_BUILDER_INTENT_CACHE_HMAC_KEY_VERSION
$previousIntentCacheProductionReady = $env:AGENT_BUILDER_INTENT_CACHE_PRODUCTION_READY
$gatewayProcess = $null
$frontendProcess = $null

try {
    $env:PYTHONPATH = $ProjectRoot
    $env:WATCHFILES_FORCE_POLLING = 'true'
    $env:WATCHFILES_IGNORE_PERMISSION_DENIED = 'true'
    $env:PYTHONUTF8 = '1'
    $env:NODE_ENV = 'development'
    $env:NEXT_PUBLIC_API_URL = 'http://localhost'
    $env:API_URL = 'http://localhost:8000'
    $LocalIntentCacheRedisUrl = 'redis://127.0.0.1:6379/15'
    $LocalIntentCacheHmacKeyVersion = 'dev-local-v1'
    $LocalIntentCacheHmacKeyBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($LocalIntentCacheHmacKeyBytes)
    $env:AGENT_BUILDER_INTENT_CACHE_ENABLED = 'true'
    $env:AGENT_BUILDER_INTENT_CACHE_REDIS_URL = $LocalIntentCacheRedisUrl
    $env:AGENT_BUILDER_INTENT_CACHE_HMAC_KEY = [Convert]::ToBase64String($LocalIntentCacheHmacKeyBytes)
    $env:AGENT_BUILDER_INTENT_CACHE_HMAC_KEY_VERSION = $LocalIntentCacheHmacKeyVersion
    $env:AGENT_BUILDER_INTENT_CACHE_PRODUCTION_READY = 'false'

    $reloadExcludedDirectories = @(
        '.pytest_cache',
        '.venv',
        '__pycache__',
        'moduly_shared.egg-info',
        'static',
        'tests'
    )
    $gatewayReloadDirectories = @(
        Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'apps/gateway') -Directory |
            Where-Object { $_.Name -notin $reloadExcludedDirectories } |
            Select-Object -ExpandProperty FullName
        Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'apps/shared') -Directory |
            Where-Object { $_.Name -notin $reloadExcludedDirectories } |
            Select-Object -ExpandProperty FullName
    )
    $gatewayArguments = @('-m', 'uvicorn', 'apps.gateway.main:app', '--reload')
    foreach ($reloadDirectory in $gatewayReloadDirectories) {
        $gatewayArguments += @('--reload-dir', $reloadDirectory)
    }
    $gatewayArguments += @('--host', '0.0.0.0', '--port', '8000')

    Write-Host 'Starting local Gateway with reload...'
    $gatewayProcess = Start-Process -FilePath $PythonExe -ArgumentList $gatewayArguments -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $gatewayOut -RedirectStandardError $gatewayErr

    Write-Host 'Starting local Frontend with hot reload...'
    $frontendProcess = Start-Process -FilePath 'npm.cmd' -ArgumentList @(
        'run', 'dev', '--', '--webpack', '--hostname', '0.0.0.0', '--port', '3000'
    ) -WorkingDirectory $ClientDirectory -PassThru -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:WATCHFILES_FORCE_POLLING = $previousWatchfilesPolling
    $env:WATCHFILES_IGNORE_PERMISSION_DENIED = $previousWatchfilesIgnorePermissionDenied
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:NODE_ENV = $previousNodeEnv
    $env:NEXT_PUBLIC_API_URL = $previousNextPublicApiUrl
    $env:API_URL = $previousApiUrl
    $env:AGENT_BUILDER_INTENT_CACHE_ENABLED = $previousIntentCacheEnabled
    $env:AGENT_BUILDER_INTENT_CACHE_REDIS_URL = $previousIntentCacheRedisUrl
    $env:AGENT_BUILDER_INTENT_CACHE_HMAC_KEY = $previousIntentCacheHmacKey
    $env:AGENT_BUILDER_INTENT_CACHE_HMAC_KEY_VERSION = $previousIntentCacheHmacKeyVersion
    $env:AGENT_BUILDER_INTENT_CACHE_PRODUCTION_READY = $previousIntentCacheProductionReady
}

Save-RecordedState -GatewayProcess $gatewayProcess -FrontendProcess $frontendProcess

try {
    Wait-ForHttp -Uri 'http://127.0.0.1:8000/api/v1/health' -ServiceName 'Gateway' -TimeoutSeconds $StartupTimeoutSeconds
    Wait-ForHttp -Uri 'http://127.0.0.1:3000' -ServiceName 'Frontend' -TimeoutSeconds $StartupTimeoutSeconds
    Ensure-LocalProxy
} catch {
    Stop-RecordedEnvironment
    throw
}

Write-Host ''
Write-Host 'Local development environment is ready:'
Write-Host '  App:      http://localhost'
Write-Host '  Frontend: http://localhost:3000'
Write-Host '  Gateway:  http://localhost:8000'
Write-Host '  Swagger:  http://localhost:8000/docs'
Write-Host '  Sandbox:  http://localhost:8194'
Write-Host "  Logs:     $RunDirectory"
Write-Host ''
Write-Host 'Gateway and Frontend are local reloadable processes. PostgreSQL, Redis, and Sandbox remain in Docker.'

if ($Detach) {
    Write-Host 'The environment is detached. Stop local processes with .\scripts\dev-local.ps1 -Stop.'
    exit 0
}

Write-Host 'Press Ctrl+C to stop the local Gateway and Frontend. Docker infrastructure remains running.'
try {
    while ($true) {
        if ($gatewayProcess.HasExited -or $frontendProcess.HasExited) {
            throw 'A required local development process exited. Check the dev-local log files.'
        }
        Start-Sleep -Seconds 2
    }
} finally {
    Stop-RecordedEnvironment
}
