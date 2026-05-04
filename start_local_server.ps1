# ============================================================
# Solardeye - Local Preview Launcher (PowerShell)
# Runs the Flask app on http://localhost:5000 using .env.local
# (uses local SQLite DB so production data stays safe)
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Solardeye - Local Preview Launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1) Ensure Python is available
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[X] Python not found. Install Python 3.11 from python.org" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# 2) Create venv if missing
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[*] Creating virtual environment .venv ..." -ForegroundColor Yellow
    python -m venv .venv
}

# 3) Activate venv
& ".venv\Scripts\Activate.ps1"

# 4) Install dependencies
Write-Host "[*] Installing dependencies (first run takes a minute) ..." -ForegroundColor Yellow
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt

# 5) Load .env.local into the current process environment
$envFile = Join-Path $PSScriptRoot ".env.local"
if (Test-Path $envFile) {
    Write-Host "[*] Loading .env.local ..." -ForegroundColor Yellow
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line -split "=", 2
            $name  = $parts[0].Trim()
            $value = $parts[1].Trim()
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
} else {
    Write-Host "[!] .env.local not found - using defaults" -ForegroundColor Yellow
}

# 6) Open browser after the server boots
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 4
    Start-Process "http://localhost:5000"
} | Out-Null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Starting Flask on http://localhost:5000" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop the server" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

python app.py
