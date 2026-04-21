@echo off
setlocal
cd /d "%~dp0"
title auto-cae launcher

if not exist ".venv\Scripts\activate.bat" (
  echo [!] .venv not found. First-time setup:
  echo     python -m venv .venv
  echo     .venv\Scripts\activate
  echo     pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo [i] Installing node deps...
  call pnpm install
  if errorlevel 1 goto :fail
)

echo [i] Starting API window...
start "auto-cae api" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && pnpm dev:api"

echo [i] Starting Web window (auto-opens browser when ready)...
start "auto-cae web" cmd /k "cd /d %~dp0 && pnpm --filter web dev --open"

echo.
echo Two server windows are running. Close them (or Ctrl+C) to stop.
exit /b 0

:fail
echo.
echo [!] startup failed.
pause
exit /b 1
