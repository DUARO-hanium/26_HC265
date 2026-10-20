#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SERVER_ENV_FILE:-$ROOT/server/server.env}"
[[ -f "$ENV_FILE" ]] || { echo "Copy server/server.env.example to server/server.env" >&2; exit 2; }
# shellcheck disable=SC1090
source "$ENV_FILE"
"${PYTHON_BIN:-python3}" -m venv "$SERVER_VENV"
"$SERVER_VENV/bin/python" -m pip install --upgrade pip
"$SERVER_VENV/bin/pip" install 'lerobot[async]==0.6.0'
"$SERVER_VENV/bin/python" -c 'import lerobot; assert lerobot.__version__ == "0.6.0"; print("LeRobot", lerobot.__version__)'
