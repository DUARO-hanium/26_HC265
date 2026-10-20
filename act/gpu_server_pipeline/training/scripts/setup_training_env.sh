#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
load_training_env "$@"

PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null || { echo "Python not found: $PYTHON_BIN" >&2; exit 2; }

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$TRAINING_DIR/requirements-training.txt"

"$VENV_DIR/bin/python" - <<'PY'
from importlib.metadata import version
assert version("lerobot") == "0.6.0", version("lerobot")
print("LeRobot", version("lerobot"))
print("Accelerate", version("accelerate"))
print("PyTorch", version("torch"))
PY
