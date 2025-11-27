@echo off
setlocal

echo Stopping development servers...

REM Find and kill processes on port 8866 (backend)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8866 ^| findstr LISTENING') do (
    echo Stopping backend process %%a...
    taskkill /PID %%a /F >nul 2>&1
)

REM Find and kill processes on port 5173 (frontend)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5173 ^| findstr LISTENING') do (
    echo Stopping frontend process %%a...
    taskkill /PID %%a /F >nul 2>&1
)

REM Also try to kill by process name
taskkill /IM uvicorn.exe /F >nul 2>&1
taskkill /IM node.exe /F >nul 2>&1

echo Done. All development servers stopped.
pause

