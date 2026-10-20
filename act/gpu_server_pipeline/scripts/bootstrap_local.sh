#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env

command -v python3.12 >/dev/null || {
  echo "Python 3.12 is required (Ubuntu 24.04 default)." >&2; exit 2;
}
if [[ ! -x "$LOCAL_VENV/bin/python" ]]; then
  python3.12 -m venv --system-site-packages "$LOCAL_VENV"
fi
"$LOCAL_VENV/bin/python" -m pip install --upgrade pip setuptools wheel
"$LOCAL_VENV/bin/python" -m pip install -e "$PROJECT_ROOT[dev,conversion]"
"$LOCAL_VENV/bin/python" - <<'PY'
import lerobot
assert lerobot.__version__ == "0.6.0", lerobot.__version__
print("LOCAL_RUNTIME_OK", lerobot.__version__)
PY
