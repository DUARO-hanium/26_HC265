#!/usr/bin/env bash
set -Eeuo pipefail

TRAINING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for script in "$TRAINING_DIR"/scripts/*.sh "$0"; do
  bash -n "$script"
done
python3 -m py_compile "$TRAINING_DIR/accelerate_nccl_smoke.py"

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/data"
sed \
  -e "s|^WORK_ROOT=.*|WORK_ROOT=\"$test_root/runtime\"|" \
  -e "s|^VENV_DIR=.*|VENV_DIR=\"$test_root/venv\"|" \
  -e "s|^DATASET_ROOT=.*|DATASET_ROOT=\"$test_root/data\"|" \
  -e "s|^OUTPUT_DIR=.*|OUTPUT_DIR=\"$test_root/output\"|" \
  -e 's|^DATASET_REPO_ID=.*|DATASET_REPO_ID="example/test"|' \
  "$TRAINING_DIR/training.env.example" > "$test_root/training.env"

output="$(PRINT_ONLY=true "$TRAINING_DIR/scripts/train_act_ddp.sh" --env-file "$test_root/training.env")"
grep -F -- '--multi_gpu' <<< "$output" >/dev/null
grep -F -- '--num_processes=2' <<< "$output" >/dev/null
grep -F -- '--policy.type=act' <<< "$output" >/dev/null
grep -F -- '--dataset.repo_id=example/test' <<< "$output" >/dev/null
grep -F -- '--batch_size=4' <<< "$output" >/dev/null
grep -F -- '--save_freq=2500' <<< "$output" >/dev/null
if grep -F 'WANDB_API_KEY' <<< "$output" >/dev/null; then
  echo "Secret variable leaked into printed command" >&2
  exit 1
fi

echo "training script tests passed"
