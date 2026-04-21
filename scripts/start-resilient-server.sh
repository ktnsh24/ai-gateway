#!/usr/bin/env bash
# Auto-restart wrapper for rag-chatbot server during lab runs.
# Restarts the server if it crashes, with a brief cooldown.
set -u

MAX_RESTARTS=10
RESTART_DELAY=5
restart_count=0

cd "$(dirname "$0")/.." || exit 1

while [ "$restart_count" -lt "$MAX_RESTARTS" ]; do
    echo "🚀 Starting rag-chatbot server (attempt $((restart_count + 1))/$MAX_RESTARTS)..."
    poetry run python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --log-level info
    exit_code=$?

    if [ "$exit_code" -eq 0 ]; then
        echo "✅ Server exited cleanly (code 0)."
        break
    fi

    restart_count=$((restart_count + 1))
    echo "⚠️  Server crashed (exit code $exit_code). Restart $restart_count/$MAX_RESTARTS in ${RESTART_DELAY}s..."
    sleep "$RESTART_DELAY"
done

if [ "$restart_count" -ge "$MAX_RESTARTS" ]; then
    echo "❌ Server crashed $MAX_RESTARTS times. Giving up."
    exit 1
fi
