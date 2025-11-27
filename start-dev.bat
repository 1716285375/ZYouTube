@echo off
setlocal

echo Starting backend (FastAPI)...
start "Backend" cmd /k "cd /d %~dp0backend && uv run uvicorn app.main:app --reload --port 8866"

echo Starting frontend (Vite)...
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo Both servers launched in separate windows.
endlocal

