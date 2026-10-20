#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
load_training_env "$@"
prepare_runtime

[[ -d "$DATASET_ROOT" ]] || { echo "Dataset root not found: $DATASET_ROOT" >&2; exit 2; }
if [[ "${PRINT_ONLY:-false}" != "true" ]]; then
  require_training_binaries
fi
accelerate_prefix

TRAIN_ARGS=(
  "$VENV_DIR/bin/lerobot-train"
  --dataset.repo_id="$DATASET_REPO_ID"
  --dataset.root="$DATASET_ROOT"
  --dataset.eval_split="$EVAL_SPLIT"
  --policy.type=act
  --policy.device=cuda
  --policy.push_to_hub=false
  --batch_size="$BATCH_SIZE_PER_GPU"
  --steps="$STEPS"
  --seed="$SEED"
  --log_freq="$LOG_FREQ"
  --eval_steps="$EVAL_STEPS"
  --max_eval_samples="$MAX_EVAL_SAMPLES"
  --save_checkpoint=true
  --save_freq="$SAVE_FREQ"
  --output_dir="$OUTPUT_DIR"
  --job_name="$JOB_NAME"
  --wandb.enable="$WANDB_ENABLE"
)
[[ -z "${DATASET_REVISION:-}" ]] || TRAIN_ARGS+=(--dataset.revision="$DATASET_REVISION")
if [[ "$WANDB_ENABLE" == "true" ]]; then
  TRAIN_ARGS+=(
    --wandb.project="$WANDB_PROJECT"
    --wandb.disable_artifact=true
    --wandb.notes="$WANDB_NOTES"
  )
fi

LOG_FILE="$WORK_ROOT/logs/${JOB_NAME}.log"
PID_FILE="$WORK_ROOT/run/${JOB_NAME}.pid"
if [[ "${PRINT_ONLY:-false}" == "true" ]]; then
  print_shell_command "${ACCELERATE_ARGS[@]}" "${TRAIN_ARGS[@]}"
  exit 0
fi

printf '%s\n' "$$" > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT
echo "Global batch size: $((BATCH_SIZE_PER_GPU * NUM_PROCESSES))"
echo "Output: $OUTPUT_DIR"
"${ACCELERATE_ARGS[@]}" "${TRAIN_ARGS[@]}" 2>&1 | tee "$LOG_FILE"
