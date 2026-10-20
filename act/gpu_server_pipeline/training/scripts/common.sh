#!/usr/bin/env bash

set -Eeuo pipefail

TRAINING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_ENV_FILE="$TRAINING_DIR/training.env"

load_training_env() {
  local env_file="${TRAIN_ENV_FILE:-$DEFAULT_ENV_FILE}"
  if [[ "${1:-}" == "--env-file" ]]; then
    [[ $# -ge 2 ]] || { echo "--env-file requires a path" >&2; return 2; }
    env_file="$2"
  elif [[ $# -gt 0 ]]; then
    echo "Unknown argument: $1" >&2
    return 2
  fi

  [[ -f "$env_file" ]] || {
    echo "Training configuration not found: $env_file" >&2
    echo "Copy $TRAINING_DIR/training.env.example to $DEFAULT_ENV_FILE and edit it." >&2
    return 2
  }
  # shellcheck disable=SC1090
  source "$env_file"
  TRAIN_ENV_FILE="$env_file"

  : "${WORK_ROOT:?WORK_ROOT must be set in $env_file}"
  : "${VENV_DIR:?VENV_DIR must be set in $env_file}"
  : "${DATASET_ROOT:?DATASET_ROOT must be set in $env_file}"
  : "${DATASET_REPO_ID:?DATASET_REPO_ID must be set in $env_file}"
  : "${OUTPUT_DIR:?OUTPUT_DIR must be set in $env_file}"

  GPU_IDS="${GPU_IDS:-0}"
  NUM_PROCESSES="${NUM_PROCESSES:-1}"
  MIXED_PRECISION="${MIXED_PRECISION:-no}"
  DYNAMO_BACKEND="${DYNAMO_BACKEND:-no}"
  BATCH_SIZE_PER_GPU="${BATCH_SIZE_PER_GPU:-8}"
  STEPS="${STEPS:-100000}"
  SEED="${SEED:-1000}"
  EVAL_SPLIT="${EVAL_SPLIT:-0.10}"
  LOG_FREQ="${LOG_FREQ:-100}"
  EVAL_STEPS="${EVAL_STEPS:-2500}"
  MAX_EVAL_SAMPLES="${MAX_EVAL_SAMPLES:-0}"
  SAVE_FREQ="${SAVE_FREQ:-2500}"
  JOB_NAME="${JOB_NAME:-act_run}"
  WANDB_ENABLE="${WANDB_ENABLE:-false}"
  WANDB_PROJECT="${WANDB_PROJECT:-lerobot-act}"
  WANDB_NOTES="${WANDB_NOTES:-LeRobot 0.6.0 ACT with official Accelerate DDP}"
  TMUX_SESSION="${TMUX_SESSION:-lerobot_act}"
  GPU_MONITOR_INTERVAL_S="${GPU_MONITOR_INTERVAL_S:-60}"
  GPU_TEMP_WARNING_C="${GPU_TEMP_WARNING_C:-85}"
  GPU_TEMP_CRITICAL_C="${GPU_TEMP_CRITICAL_C:-90}"

  local visible_count
  IFS=',' read -r -a _gpu_array <<< "$GPU_IDS"
  visible_count="${#_gpu_array[@]}"
  [[ "$NUM_PROCESSES" =~ ^[1-9][0-9]*$ ]] || {
    echo "NUM_PROCESSES must be a positive integer" >&2; return 2;
  }
  (( visible_count >= NUM_PROCESSES )) || {
    echo "GPU_IDS exposes $visible_count GPU(s), fewer than NUM_PROCESSES=$NUM_PROCESSES" >&2
    return 2
  }
  [[ "$WANDB_ENABLE" == "true" || "$WANDB_ENABLE" == "false" ]] || {
    echo "WANDB_ENABLE must be true or false" >&2; return 2;
  }
}

prepare_runtime() {
  mkdir -p \
    "$WORK_ROOT/cache/huggingface" \
    "$WORK_ROOT/cache/torch" \
    "$WORK_ROOT/cache/pip" \
    "$WORK_ROOT/cache/tmp" \
    "$WORK_ROOT/cache/wandb/data" \
    "$WORK_ROOT/logs" \
    "$WORK_ROOT/run" \
    "$(dirname "$OUTPUT_DIR")"

  export CUDA_VISIBLE_DEVICES="$GPU_IDS"
  export HF_HOME="$WORK_ROOT/cache/huggingface"
  export HF_HUB_CACHE="$WORK_ROOT/cache/huggingface/hub"
  export TORCH_HOME="$WORK_ROOT/cache/torch"
  export PIP_CACHE_DIR="$WORK_ROOT/cache/pip"
  export TMPDIR="$WORK_ROOT/cache/tmp"
  export WANDB_CACHE_DIR="$WORK_ROOT/cache/wandb"
  export WANDB_DATA_DIR="$WORK_ROOT/cache/wandb/data"
  export WANDB_DIR="$WORK_ROOT/logs"
  export PYTHONUNBUFFERED=1

  if [[ "$WANDB_ENABLE" == "true" && -z "${WANDB_API_KEY:-}" ]]; then
    if [[ -n "${WANDB_API_KEY_FILE:-}" && -s "$WANDB_API_KEY_FILE" ]]; then
      WANDB_API_KEY="$(<"$WANDB_API_KEY_FILE")"
      export WANDB_API_KEY
    else
      echo "W&B is enabled, but WANDB_API_KEY is unset and WANDB_API_KEY_FILE is missing/empty." >&2
      return 2
    fi
  fi
}

require_training_binaries() {
  [[ -x "$VENV_DIR/bin/accelerate" ]] || {
    echo "Missing $VENV_DIR/bin/accelerate; run scripts/setup_training_env.sh first." >&2
    return 2
  }
  [[ -x "$VENV_DIR/bin/lerobot-train" ]] || {
    echo "Missing $VENV_DIR/bin/lerobot-train; run scripts/setup_training_env.sh first." >&2
    return 2
  }
}

accelerate_prefix() {
  ACCELERATE_ARGS=(
    "$VENV_DIR/bin/accelerate" launch
    --num_processes="$NUM_PROCESSES"
    --num_machines=1
    --mixed_precision="$MIXED_PRECISION"
    --dynamo_backend="$DYNAMO_BACKEND"
  )
  if (( NUM_PROCESSES > 1 )); then
    ACCELERATE_ARGS+=(--multi_gpu)
  fi
}

print_shell_command() {
  printf '%q ' "$@"
  printf '\n'
}
