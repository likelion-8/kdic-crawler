[CmdletBinding()]
param(
    [string] $MemberName
)

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

function ConvertTo-SqlLiteral {
    param([Parameter(Mandatory)][string] $Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function ConvertFrom-SecureString {
    param([Parameter(Mandatory)][Security.SecureString] $Value)

    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw '.env does not exist. Create it from .env.example first.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI was not found. Install and start Docker Desktop first.'
}
if ([string]::IsNullOrWhiteSpace($MemberName)) {
    $MemberName = Read-Host 'Team account name (for example: kdic_member1)'
}
if ($MemberName -notmatch '^kdic_[a-z0-9_]+$') {
    throw 'Account names must start with kdic_ and contain only lowercase letters, digits, and underscores.'
}

$databaseName = Get-EnvValue -Name 'POSTGRES_DB'
$adminUser = Get-EnvValue -Name 'POSTGRES_USER'
$adminPassword = Get-EnvValue -Name 'POSTGRES_PASSWORD'
if ([string]::IsNullOrWhiteSpace($adminPassword) -or $adminPassword -ceq 'CHANGE_ME') {
    throw 'POSTGRES_PASSWORD must be set in .env before creating an account.'
}

$health = & docker inspect --format '{{.State.Health.Status}}' $containerName 2>$null
if ($LASTEXITCODE -ne 0 -or $health -ne 'healthy') {
    throw "$containerName is not healthy. Run scripts\start.ps1 first."
}

$memberPassword = $null
Push-Location $projectRoot
try {
    $memberNameLiteral = ConvertTo-SqlLiteral -Value $MemberName
    $existsSql = "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $memberNameLiteral);"
    $exists = $existsSql | & docker compose --env-file .env exec -T -e "PGPASSWORD=$adminPassword" database psql -X -h 127.0.0.1 -U $adminUser -d $databaseName -tA -v ON_ERROR_STOP=1 -f - 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not check whether the requested account already exists.'
    }
    if ($exists -contains 't') {
        Write-Warning "$MemberName already exists. Its password and attributes were not changed."
        exit 0
    }

    $firstSecure = Read-Host "Password for $MemberName" -AsSecureString
    $secondSecure = Read-Host 'Enter the same password again' -AsSecureString
    $memberPassword = ConvertFrom-SecureString -Value $firstSecure
    $confirmationPassword = ConvertFrom-SecureString -Value $secondSecure
    try {
        if ([string]::IsNullOrEmpty($memberPassword)) {
            throw 'Password must not be empty.'
        }
        if ($memberPassword -cne $confirmationPassword) {
            throw 'The two password entries do not match. No account was created.'
        }
    }
    finally {
        $confirmationPassword = $null
    }

    $memberPasswordLiteral = ConvertTo-SqlLiteral -Value $memberPassword
    $creationSql = @(
        '\set ON_ERROR_STOP on'
        '\set QUIET on'
        'BEGIN;'
        "SET LOCAL password_encryption = 'scram-sha-256';"
        "SELECT set_config('kdic.member_name', $memberNameLiteral, true);"
        "SELECT set_config('kdic.member_password', $memberPasswordLiteral, true);"
        'DO $create_team_member$'
        'DECLARE'
        "    requested_name text := current_setting('kdic.member_name');"
        "    requested_password text := current_setting('kdic.member_password');"
        'BEGIN'
        "    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = requested_name) THEN"
        "        RAISE EXCEPTION 'Role % already exists; no changes were made.', requested_name;"
        '    END IF;'
        "    EXECUTE format('CREATE ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', requested_name, requested_password);"
        "    EXECUTE format('GRANT kdic_team_admin TO %I WITH INHERIT TRUE, SET TRUE', requested_name);"
        'END'
        '$create_team_member$;'
        'COMMIT;'
    ) -join [Environment]::NewLine
    $creationSql | & docker compose --env-file .env exec -T -e "PGPASSWORD=$adminPassword" database psql -q -X -h 127.0.0.1 -U $adminUser -d $databaseName -v ON_ERROR_STOP=1 -f - 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create $MemberName."
    }

    $roleCheckSql = "SELECT r.rolcanlogin, r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls, a.inherit_option, a.set_option, auth.rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_roles AS r JOIN pg_auth_members AS a ON a.member = r.oid JOIN pg_roles AS parent ON parent.oid = a.roleid JOIN pg_authid AS auth ON auth.oid = r.oid WHERE r.rolname = $memberNameLiteral AND parent.rolname = 'kdic_team_admin';"
    $roleCheck = $roleCheckSql | & docker compose --env-file .env exec -T -e "PGPASSWORD=$adminPassword" database psql -X -h 127.0.0.1 -U $adminUser -d $databaseName -tA -F '|' -v ON_ERROR_STOP=1 -f - 2>&1
    if ($LASTEXITCODE -ne 0 -or $roleCheck -notcontains 't|f|f|f|f|f|t|t|t') {
        throw "Role security or group-membership verification failed for $MemberName."
    }

    $loginCheck = & docker compose --env-file .env exec -T -e "PGPASSWORD=$memberPassword" database psql -X -h 127.0.0.1 -U $MemberName -d $databaseName -tA -v ON_ERROR_STOP=1 -c 'SELECT current_user;' 2>&1
    if ($LASTEXITCODE -ne 0 -or $loginCheck -notcontains $MemberName) {
        throw "Password login verification failed for $MemberName."
    }

    Write-Host "$MemberName was created with a SCRAM-SHA-256 password and kdic_team_admin membership."
    Write-Host 'Its password was not printed or written to a file.'
}
finally {
    $memberPassword = $null
    $adminPassword = $null
    Pop-Location
}
