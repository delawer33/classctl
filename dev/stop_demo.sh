#!/usr/bin/env bash
# Tears down the demo environment created by start_demo.sh
set -euo pipefail

echo "Stopping containers…"
docker rm -f ws-1 ws-2 ws-3 2>/dev/null || true

echo "Removing network…"
docker network rm classctl-demo 2>/dev/null || true

echo "✓  Demo environment stopped."
