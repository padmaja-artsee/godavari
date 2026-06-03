#!/usr/bin/env bash
# Stop all Godavari Leads desktop / backend processes (macOS).
set -euo pipefail

echo "Stopping Godavari Leads processes..."
pkill -9 -f "GodavariLeads" 2>/dev/null || true
pkill -9 -f "leads-bin/leads" 2>/dev/null || true
pkill -9 -f "Contents/MacOS/leads" 2>/dev/null || true
pkill -9 -f "uvicorn app.main" 2>/dev/null || true

for port in 8000 8001 8002; do
  lsof -ti "tcp:${port}" 2>/dev/null | xargs kill -9 2>/dev/null || true
done

sleep 1
if pgrep -lf "GodavariLeads|leads-bin/leads|uvicorn app.main" >/dev/null 2>&1; then
  echo "Some processes may still be running:"
  pgrep -lf "GodavariLeads|leads-bin/leads|uvicorn app.main" || true
else
  echo "Done — port 8000 should be free."
fi
