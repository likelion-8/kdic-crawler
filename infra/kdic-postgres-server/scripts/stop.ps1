[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw '.env does not exist.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. Install and start Docker Desktop first.'
}

Push-Location $projectRoot
try {
    & docker compose --env-file .env stop
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose stop failed.'
    }
    Write-Host 'kdic-postgres16 stopped. The container and data volume were preserved.'
}
finally {
    Pop-Location
}
