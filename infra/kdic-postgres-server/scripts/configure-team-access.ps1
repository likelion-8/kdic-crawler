[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
$roleSqlFile = Join-Path $projectRoot 'db\init\03_team_role.sql'
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
    throw '.env does not exist. Create it from .env.example first.'
}
if (-not (Test-Path -LiteralPath $roleSqlFile -PathType Leaf)) {
    throw "Team-role SQL file is missing: $roleSqlFile"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. Install and start Docker Desktop first.'
}

$databaseName = Get-EnvValue -Name 'POSTGRES_DB'
$adminUser = Get-EnvValue -Name 'POSTGRES_USER'
$adminPassword = Get-EnvValue -Name 'POSTGRES_PASSWORD'
if ([string]::IsNullOrWhiteSpace($adminPassword) -or $adminPassword -ceq 'CHANGE_ME') {
    throw 'POSTGRES_PASSWORD must be set in .env before configuring access.'
}

$health = & docker inspect --format '{{.State.Health.Status}}' $containerName 2>$null
if ($LASTEXITCODE -ne 0 -or $health -ne 'healthy') {
    throw "$containerName is not healthy. Run scripts\start.ps1 first."
}

Push-Location $projectRoot
try {
    $roleSql = Get-Content -LiteralPath $roleSqlFile -Raw
    $roleSql | & docker compose --env-file .env exec -T -e "PGPASSWORD=$adminPassword" database psql -X -h 127.0.0.1 -U $adminUser -d $databaseName -v ON_ERROR_STOP=1 -f - 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Team role and privilege configuration failed.'
    }

    $checkSql = "SELECT r.rolcanlogin, r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls, has_schema_privilege('kdic_team_admin', 'public', 'USAGE,CREATE') FROM pg_roles AS r WHERE r.rolname = 'kdic_team_admin';"
    $roleCheck = $checkSql | & docker compose --env-file .env exec -T -e "PGPASSWORD=$adminPassword" database psql -X -h 127.0.0.1 -U $adminUser -d $databaseName -tA -F '|' -v ON_ERROR_STOP=1 -f - 2>&1
    if ($LASTEXITCODE -ne 0 -or $roleCheck -notcontains 'f|f|f|f|f|f|t') {
        throw 'Team role security or public-schema privilege verification failed.'
    }

    Write-Host 'kdic_team_admin role and existing public-schema privileges are configured.'
    Write-Host 'No tables or application data were deleted.'
}
finally {
    $adminPassword = $null
    Pop-Location
}
