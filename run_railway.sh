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

# Bridge defaults for cloud deployments (override via Railway variables).
export SCRAPER_BRIDGE_URL="${SCRAPER_BRIDGE_URL:-${BRIDGE_URL:-http://127.0.0.1:8000}}"
export API_SECRET="${BRIDGE_SHARED_SECRET:-${API_SECRET:-secreto123}}"
export BRIDGE_VERIFY_SSL="${BRIDGE_VERIFY_SSL:-false}"

exec python3 main.py