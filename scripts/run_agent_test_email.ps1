param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$Etf = "00981A",
    [string]$Receiver = "jabir95tsai@gmail.com",
    [switch]$NotifyOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path $Python)) {
    $Python = "python"
}

# Use .env for Gmail credentials, but force all generated files into data/test.
Remove-Item Env:\ENV_FILE -ErrorAction SilentlyContinue
$env:ETF_CODE = $Etf
$env:DB_PATH = "data/test/etf_holdings_test.sqlite"
$env:RAW_DIR = "data/test/raw"
$env:REPORT_DIR = "data/test/reports"
$env:GMAIL_RECEIVER_EMAILS = $Receiver
$env:NOTIFY_ON_NO_UPDATE = "false"
$env:SOURCE_ORDER = "moneydj,ezmoney,official,twse"

if ($NotifyOnly) {
    & $Python -m src.main --etf $Etf --notify-test
} else {
    & $Python -m src.main --etf $Etf --force-report
}
