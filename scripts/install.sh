#!/usr/bin/env bash
# One-shot setup: create a venv and install dependencies (POSIX systems (Linux/macOS)).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$ROOT/requirements-test.txt"
printf 'Install complete. Activate with: source "%s/bin/activate"\n' "$VENV_DIR"
