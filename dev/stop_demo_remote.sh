#!/usr/bin/env bash
set -euo pipefail

echo "Stopping containers…"
docker rm -f ws-1 ws-2 ws-3 2>/dev/null || true

echo "✓  Remote demo environment stopped."
