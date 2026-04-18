# Goblin Guardian: One-Command Setup
# Run this from the repository root to install all dev tools and activate Guardian hooks.
#
# Usage:
#   .\scripts\setup-guardian.ps1

$ErrorActionPreference = "Stop"

Write-Host "`n=== Goblin Guardian Setup ===" -ForegroundColor Cyan

# Install the project with dev dependencies
Write-Host "`n[1/3] Installing project with dev dependencies..." -ForegroundColor Yellow
pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: pip install failed." -ForegroundColor Red
    exit 1
}

# Install pre-commit hooks (commit + push)
Write-Host "`n[2/3] Installing pre-commit hooks..." -ForegroundColor Yellow
pre-commit install
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: pre-commit install failed." -ForegroundColor Red
    exit 1
}

pre-commit install --hook-type pre-push
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: pre-push hook install failed (non-critical on Windows)." -ForegroundColor DarkYellow
}

# Verify
Write-Host "`n[3/3] Verifying setup..." -ForegroundColor Yellow
$ruffVersion = ruff --version 2>&1
$pytestVersion = python -m pytest --version 2>&1
Write-Host "  ruff:       $ruffVersion"
Write-Host "  pytest:     $($pytestVersion -split "`n" | Select-Object -First 1)"
Write-Host "  pre-commit: $(pre-commit --version)"

Write-Host "`n=== Guardian is watching. Your coins are safe! ===" -ForegroundColor Green
