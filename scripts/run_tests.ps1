param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:ENV_FILE = ".env.test"
& $Python -m pytest -q tests
