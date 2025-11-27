#!/usr/bin/env bash

set -euo pipefail

echo "Starting backend (FastAPI + uvicorn)..."
(
  cd backend
  uv run uvicorn app.main:app --reload --port 8866
) &
BACKEND_PID=$!

echo "Starting frontend (Vite dev server)..."
(
  cd frontend
  npm run dev
) &
FRONTEND_PID=$!

cleanup() {
  echo "Stopping services..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}

trap cleanup INT TERM

wait "$BACKEND_PID" "$FRONTEND_PID"

