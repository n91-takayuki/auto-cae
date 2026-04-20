# Auto-CAE dependency installer (Windows / PowerShell)
# Assumes: winget available, network access
# Run from repo root:  powershell -ExecutionPolicy Bypass -File .\scripts\install-deps.ps1

$ErrorActionPreference = "Stop"

Write-Host "== Auto-CAE dependency installer ==" -ForegroundColor Cyan

function Have($cmd) {
  return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

# ---- Node & pnpm ---------------------------------------------------------
if (-not (Have node)) {
  Write-Host "-- Installing Node.js LTS" -ForegroundColor Yellow
  winget install -e --id OpenJS.NodeJS.LTS --silent --accept-source-agreements --accept-package-agreements
} else {
  Write-Host "[ok] node: $(node -v)"
}

if (-not (Have pnpm)) {
  Write-Host "-- Enabling pnpm via corepack"
  corepack enable
  corepack prepare pnpm@9.12.0 --activate
} else {
  Write-Host "[ok] pnpm: $(pnpm -v)"
}

# ---- Miniconda -----------------------------------------------------------
if (-not (Have conda)) {
  Write-Host "-- Installing Miniconda" -ForegroundColor Yellow
  winget install -e --id Anaconda.Miniconda3 --silent --accept-source-agreements --accept-package-agreements
  Write-Host "   PowerShell を再起動してから再度実行してください。" -ForegroundColor Yellow
  exit 0
}

# ---- conda env: cae ------------------------------------------------------
$envName = "cae"
$envExists = (conda env list) -match "^\s*$envName\s"
if (-not $envExists) {
  Write-Host "-- Creating conda env '$envName'" -ForegroundColor Yellow
  conda create -y -n $envName python=3.11
}

Write-Host "-- Installing Python deps into '$envName'"
conda install -y -n $envName -c conda-forge `
  pythonocc-core gmsh numpy `
  fastapi "uvicorn-standard" websockets pydantic `
  python-multipart

# ---- CalculiX ------------------------------------------------------------
$ccxDir = "C:\cae\ccx"
if (-not (Test-Path $ccxDir)) {
  Write-Host ""
  Write-Host "CalculiX Windows binary を手動で配置してください:" -ForegroundColor Yellow
  Write-Host "  1. http://www.dhondt.de/ または https://bconverged.com から ccx Windows 版を入手"
  Write-Host "  2. ccx.exe を $ccxDir\ccx.exe に配置"
  Write-Host "  3. setx CCX_PATH `"$ccxDir\ccx.exe`"  を実行して環境変数登録"
  Write-Host ""
}

Write-Host ""
Write-Host "セットアップ完了。" -ForegroundColor Green
Write-Host "  conda activate $envName"
Write-Host "  python scripts\doctor.py"
Write-Host "  pnpm install"
