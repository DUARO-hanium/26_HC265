#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
load_training_env "$@"
prepare_runtime
require_training_binaries
accelerate_prefix

CHECKPOINT_ROOT="$OUTPUT_DIR/checkpoints"
mapfile -t NUMERIC_CHECKPOINTS < <(
  find "$CHECKPOINT_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null \
    | awk '/^[0-9]+$/' | sort -n
)
(( ${#NUMERIC_CHECKPOINTS[@]} > 0 )) || {
  echo "No numeric official checkpoint found under $CHECKPOINT_ROOT" >&2
  exit 2
}
LATEST="${NUMERIC_CHECKPOINTS[-1]}"
CONFIG="$CHECKPOINT_ROOT/$LATEST/pretrained_model/train_config.json"
[[ -f "$CONFIG" ]] || { echo "Missing checkpoint config: $CONFIG" >&2; exit 2; }

LOG_FILE="$WORK_ROOT/logs/${JOB_NAME}_resume.log"
PID_FILE="$WORK_ROOT/run/${JOB_NAME}.pid"
printf '%s\n' "$$" > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT

echo "Resuming official LeRobot checkpoint: $LATEST"
"${ACCELERATE_ARGS[@]}" \
  "$VENV_DIR/bin/lerobot-train" \
  --config_path="$CONFIG" \
  --resume=true \
  2>&1 | tee -a "$LOG_FILE"
