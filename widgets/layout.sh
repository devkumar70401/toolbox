#!/usr/bin/env bash
# Wrapper for Devendra Widgets Layout Manager
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$HOME/SE/toolbox/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="/usr/bin/python3"
fi
exec "$PYTHON_BIN" "$SCRIPT_DIR/layout.py" "$@"
