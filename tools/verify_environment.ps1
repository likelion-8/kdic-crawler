[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$AllowNodeMismatch,
    [switch]$RunTests,
    [switch]$RunFrontendChecks
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonVersion = (Get-Content (Join-Path $repoRoot '.python-version') -Raw).Trim()
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment not found: $venvPython. Run tools\setup_environment.ps1 first."
}

$pythonActual = (& $venvPython --version 2>&1).ToString().Trim()
if ($pythonActual -ne "Python $pythonVersion") {
    throw "Python version mismatch. Expected Python $pythonVersion, found $pythonActual."
}
& $venvPython -m pip check

if (-not $SkipFrontend) {
    $nodeTarget = (Get-Content (Join-Path $repoRoot 'web\.nvmrc') -Raw).Trim().TrimStart('v')
    $nodeActual = (& node.exe --version 2>&1).ToString().Trim().TrimStart('v')
    if ($nodeActual -ne $nodeTarget) {
        if ($AllowNodeMismatch) {
            Write-Warning "Node.js mismatch: expected $nodeTarget, found $nodeActual"
        } else {
            throw "Node.js version mismatch. Expected $nodeTarget, found $nodeActual. Use -AllowNodeMismatch only for a non-reproducibility smoke check."
        }
    }
    $packageJson = Get-Content (Join-Path $repoRoot 'web\package.json') -Raw | ConvertFrom-Json
    $pnpmTarget = ($packageJson.packageManager -split '@')[-1]
    $pnpmActual = (& pnpm.cmd --version 2>&1).ToString().Trim()
    if ($pnpmActual -ne $pnpmTarget) { throw "pnpm version mismatch. Expected $pnpmTarget, found $pnpmActual." }
}

if ($RunTests) {
    Push-Location $repoRoot
    try { & $venvPython -m pytest -q } finally { Pop-Location }
}

if ($RunFrontendChecks) {
    Push-Location (Join-Path $repoRoot 'web')
    try { & pnpm.cmd run verify } finally { Pop-Location }
}

Write-Host 'Environment verification passed.'
