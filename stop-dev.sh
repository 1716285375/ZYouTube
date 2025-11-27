#!/usr/bin/env bash

set -euo pipefail

echo "Stopping development servers..."

# Find and kill uvicorn processes on port 8866
UVICORN_PIDS=$(lsof -ti:8866 2>/dev/null || true)
if [ -n "$UVICORN_PIDS" ]; then
  echo "Stopping backend (uvicorn on port 8866)..."
  echo "$UVICORN_PIDS" | xargs kill -TERM 2>/dev/null || true
  sleep 1
  # Force kill if still running
  echo "$UVICORN_PIDS" | xargs kill -KILL 2>/dev/null || true
fi

# Find and kill Vite dev server processes (typically on port 5173)
VITE_PIDS=$(lsof -ti:5173 2>/dev/null || true)
if [ -n "$VITE_PIDS" ]; then
  echo "Stopping frontend (Vite on port 5173)..."
  echo "$VITE_PIDS" | xargs kill -TERM 2>/dev/null || true
  sleep 1
  # Force kill if still running
  echo "$VITE_PIDS" | xargs kill -KILL 2>/dev/null || true
fi

# Also try to kill by process name as fallback
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true

echo "Done. All development servers stopped."

