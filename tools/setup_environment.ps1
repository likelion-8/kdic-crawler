[CmdletBinding()]
param(
    [switch]$SkipFrontend
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonVersion = (Get-Content (Join-Path $repoRoot '.python-version') -Raw).Trim()
$pythonMinor = ($pythonVersion -replace '\.\d+$', '')
$venvPath = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'

function Assert-Version([string]$label, [string]$actual, [string]$expected) {
    if ($actual -ne $expected) {
        throw "$label version mismatch. Expected $expected, found $actual."
    }
}

$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $pyLauncher) {
    throw 'Python Launcher (py.exe) was not found. Install Python 3.11.9 and enable the Python Launcher.'
}

$hostPython = (& py.exe "-$pythonMinor" --version 2>&1).ToString().Trim()
Assert-Version 'Python' $hostPython "Python $pythonVersion"

if (-not (Test-Path -LiteralPath $venvPython)) {
    & py.exe "-$pythonMinor" -m venv $venvPath
}

$venvActual = (& $venvPython --version 2>&1).ToString().Trim()
Assert-Version 'Virtualenv Python' $venvActual "Python $pythonVersion"

$lockFile = Join-Path $repoRoot 'requirements-lock-py311-windows.txt'
if (-not (Test-Path -LiteralPath $lockFile)) {
    $lockFile = Join-Path $repoRoot 'requirements.txt'
}
& $venvPython -m pip install --requirement $lockFile

$envFile = Join-Path $repoRoot '.env'
$envExample = Join-Path $repoRoot '.env.example'
if (-not (Test-Path -LiteralPath $envFile) -and (Test-Path -LiteralPath $envExample)) {
    Copy-Item -LiteralPath $envExample -Destination $envFile
    Write-Warning 'Created .env from .env.example. Fill in local credentials before starting services.'
}

if (-not $SkipFrontend) {
    $nodeTarget = (Get-Content (Join-Path $repoRoot 'web\.nvmrc') -Raw).Trim().TrimStart('v')
    $nodeActual = (& node.exe --version 2>&1).ToString().Trim().TrimStart('v')
    Assert-Version 'Node.js' $nodeActual $nodeTarget

    $packageJson = Get-Content (Join-Path $repoRoot 'web\package.json') -Raw | ConvertFrom-Json
    $pnpmTarget = ($packageJson.packageManager -split '@')[-1]
    $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    $pnpmActual = if ($pnpmCommand) { (& pnpm.cmd --version 2>&1).ToString().Trim() } else { '' }
    if ($pnpmActual -ne $pnpmTarget) {
        & npm.cmd install --global "pnpm@$pnpmTarget"
    }
    $pnpmActual = (& pnpm.cmd --version 2>&1).ToString().Trim()
    Assert-Version 'pnpm' $pnpmActual $pnpmTarget

    Push-Location (Join-Path $repoRoot 'web')
    try {
        & pnpm.cmd install --frozen-lockfile
    } finally {
        Pop-Location
    }
}

Write-Host "Environment setup completed for $repoRoot"
Write-Host "Python: $pythonVersion"
if (-not $SkipFrontend) { Write-Host "Node.js: $nodeTarget; pnpm: $pnpmTarget" }
