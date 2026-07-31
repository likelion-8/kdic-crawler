[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$volumeName = 'kdic-postgres16-data'

Write-Warning "This permanently deletes all data in Docker volume '$volumeName'."
$confirmation = Read-Host 'Type RESET exactly to continue'
if ($confirmation -cne 'RESET') {
    Write-Host 'Reset cancelled. No container or volume was changed.'
    exit 1
}

Push-Location $projectRoot
try {
    & docker compose --env-file .env down --volumes
    if ($LASTEXITCODE -ne 0) {
        throw 'docker compose down --volumes failed.'
    }
    Write-Host "Container resources and volume '$volumeName' were removed."
}
finally {
    Pop-Location
}
