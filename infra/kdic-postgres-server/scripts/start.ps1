[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
$containerName = 'kdic-postgres16'

function Get-EnvValue {
    param([Parameter(Mandatory)][string] $Name)

    $escapedName = [regex]::Escape($Name)
    $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match "^\s*$escapedName\s*=" } | Select-Object -Last 1
    if (-not $line) {
        throw "$Name is missing from $envFile"
    }
    return ($line -split '=', 2)[1].Trim()
}

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw '.env does not exist. Copy .env.example to .env, set POSTGRES_PASSWORD, and retry.'
}

$adminPassword = Get-EnvValue -Name 'POSTGRES_PASSWORD'
if ([string]::IsNullOrWhiteSpace($adminPassword) -or $adminPassword -ceq 'CHANGE_ME') {
    throw 'POSTGRES_PASSWORD must be changed from CHANGE_ME before startup.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. Install and start Docker Desktop first.'
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop is not running or its daemon is unavailable.'
}

Push-Location $projectRoot
try {
    & docker compose --env-file .env config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose configuration validation failed.'
    }
    & docker compose --env-file .env up -d
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose up -d failed.'
    }

    $health = ''
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $health = & docker inspect --format '{{.State.Health.Status}}' $containerName 2>$null
        if ($LASTEXITCODE -eq 0 -and $health -eq 'healthy') {
            break
        }
        Start-Sleep -Seconds 2
    }
    if ($health -ne 'healthy') {
        & docker compose --env-file .env ps
        & docker compose --env-file .env logs --tail=100 database
        throw "$containerName did not become healthy within 120 seconds."
    }

    Write-Host "$containerName is healthy. No Docker volume was removed."
}
finally {
    $adminPassword = $null
    Pop-Location
}
