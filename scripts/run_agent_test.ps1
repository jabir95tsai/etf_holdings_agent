param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$Etf = "00981A",
    [switch]$ForceReport
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:ENV_FILE = ".env.test"
$args = @("-m", "src.main", "--etf", $Etf, "--dry-run")

if ($ForceReport) {
    $args += "--force-report"
}

& $Python @args
