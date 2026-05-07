#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WITH_SAMPLE_DATA=0
FORCE_SAMPLE_DATA=0

usage() {
  cat <<'EOF'
Usage: ./scripts/bootstrap_local.sh [--with-sample-data] [--force-sample-data] [--python /path/to/python3.11]

Options:
  --with-sample-data   Seed a minimal offline workspace after installing dependencies.
  --force-sample-data  Rebuild the sample workspace even if data/ already contains artifacts.
  --python PATH        Override the Python executable used to create .venv.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-sample-data)
      WITH_SAMPLE_DATA=1
      shift
      ;;
    --force-sample-data)
      WITH_SAMPLE_DATA=1
      FORCE_SAMPLE_DATA=1
      shift
      ;;
    --python)
      if [[ $# -lt 2 ]]; then
        echo "--python requires a value" >&2
        exit 1
      fi
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but was not found in PATH" >&2
  exit 1
fi

cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e .

if [[ -f frontend/package-lock.json ]]; then
  (
    cd frontend
    npm ci
    npm run build
  )
else
  (
    cd frontend
    npm install
    npm run build
  )
fi

if [[ "$WITH_SAMPLE_DATA" -eq 1 ]]; then
  SAMPLE_ARGS=()
  if [[ "$FORCE_SAMPLE_DATA" -eq 1 ]]; then
    SAMPLE_ARGS+=(--force)
  fi
  .venv/bin/python scripts/init_sample_workspace.py "${SAMPLE_ARGS[@]}"
fi

echo "Bootstrap complete."
echo "Start the UI with:"
echo "  .venv/bin/python -m crypto_backtest_workbench.cli ui --repository-root . --host 127.0.0.1 --port 8501"
