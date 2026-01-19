#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_DIR="$SCRIPT_DIR/setup"

export WILAB_DIR="${WILAB_DIR:-$SCRIPT_DIR}"
export VENV_PATH="${VENV_PATH:-/opt/wilab-venv}"

if [ ! -d "$STAGE_DIR" ]; then
    echo "Stage directory not found at $STAGE_DIR"
    exit 1
fi

STAGES=("$STAGE_DIR"/[0-9][0-9]-*.sh)
if [ ${#STAGES[@]} -eq 0 ] || [ ! -e "${STAGES[0]}" ]; then
    echo "No stage scripts found in $STAGE_DIR"
    exit 1
fi

for stage in "${STAGES[@]}"; do
    if [ ! -f "$stage" ]; then
        continue
    fi

    echo ""
    echo "=== Running $(basename "$stage") ==="
    bash "$stage"
done
