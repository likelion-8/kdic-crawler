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
    throw '.env does not exist. Run scripts\start.ps1 after creating it.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. Install and start Docker Desktop first.'
}

$databaseName = Get-EnvValue -Name 'POSTGRES_DB'
$adminUser = Get-EnvValue -Name 'POSTGRES_USER'
$hostPort = Get-EnvValue -Name 'POSTGRES_HOST_PORT'
$health = & docker inspect --format '{{.State.Health.Status}}' $containerName 2>$null
if ($LASTEXITCODE -ne 0 -or $health -ne 'healthy') {
    throw "$containerName is not healthy. Run scripts\start.ps1 first."
}

$tcpSucceeded = Test-NetConnection -ComputerName 127.0.0.1 -Port $hostPort -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $tcpSucceeded) {
    throw "TCP connection to 127.0.0.1:$hostPort failed."
}

function Invoke-ContainerPsql {
    param([Parameter(Mandatory)][string] $Sql)

    $result = $Sql | & docker compose --env-file .env exec -T database psql -X -U $adminUser -d $databaseName -tA -v ON_ERROR_STOP=1 -f - 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'Container psql verification command failed.'
    }
    return @($result)
}

Push-Location $projectRoot
try {
    $serverVersionResults = @(Invoke-ContainerPsql -Sql 'SHOW server_version_num;')
    $serverVersionNumber = $serverVersionResults[0].Trim()
    $majorVersion = [math]::Floor(([int]$serverVersionNumber) / 10000)
    if ($majorVersion -ne 16) {
        throw "Expected PostgreSQL major version 16, but found $majorVersion."
    }

    $serverVersionResults = @(Invoke-ContainerPsql -Sql 'SHOW server_version;')
    $serverVersion = $serverVersionResults[0].Trim()
    $pgvectorVersionResults = @(Invoke-ContainerPsql -Sql "SELECT extversion FROM pg_extension WHERE extname = 'vector';")
    $pgvectorVersion = $pgvectorVersionResults[0].Trim()
    if ($pgvectorVersion -ne '0.8.1') {
        throw "Expected pgvector 0.8.1, but found '$pgvectorVersion'."
    }

    $vectorTestSql = @(
        'BEGIN;'
        'CREATE TEMP TABLE kdic_vector_smoke_test (embedding vector(3) NOT NULL);'
        "INSERT INTO kdic_vector_smoke_test (embedding) VALUES ('[1,2,3]');"
        "SELECT (embedding <-> '[4,5,6]'::vector) > 0 FROM kdic_vector_smoke_test;"
        'DROP TABLE kdic_vector_smoke_test;'
        'COMMIT;'
    ) -join [Environment]::NewLine
    $vectorResult = Invoke-ContainerPsql -Sql $vectorTestSql
    if ($vectorResult -notcontains 't') {
        throw 'The pgvector create/insert/distance-query test failed.'
    }

    Write-Host "Container:           $containerName ($health)"
    Write-Host "127.0.0.1:${hostPort}: connected"
    Write-Host "PostgreSQL major:    $majorVersion"
    Write-Host "PostgreSQL version:  $serverVersion"
    Write-Host "pgvector version:    $pgvectorVersion"
    Write-Host 'Vector temporary object: create/insert/distance-query/drop succeeded'
}
finally {
    Pop-Location
}
