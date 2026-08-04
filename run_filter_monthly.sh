#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

exec python3 -m tools.filter_high_gs --delay 2
