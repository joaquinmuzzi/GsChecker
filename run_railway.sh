#!/bin/bash
set -euo pipefail

# Keep paths stable regardless of current working directory.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

if [[ -z "${DISCORD_TOKEN:-}" ]]; then
    echo "ERROR: DISCORD_TOKEN is required"
    exit 1
fi

exec python3 main.py