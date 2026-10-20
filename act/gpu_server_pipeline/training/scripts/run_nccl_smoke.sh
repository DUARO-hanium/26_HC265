#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
load_training_env "$@"
prepare_runtime
require_training_binaries
accelerate_prefix

exec "${ACCELERATE_ARGS[@]}" "$TRAINING_DIR/accelerate_nccl_smoke.py"
