#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
load_training_env "$@"

command -v tmux >/dev/null || { echo "tmux is required" >&2; exit 2; }
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  echo "tmux session already exists: $TMUX_SESSION" >&2
  exit 2
fi

printf -v quoted_env '%q' "$TRAIN_ENV_FILE"
printf -v quoted_train '%q' "$SCRIPT_DIR/train_act_ddp.sh"
printf -v quoted_monitor '%q' "$SCRIPT_DIR/monitor_gpu_temperature.sh"

tmux new-session -d -s "$TMUX_SESSION" -n train \
  "TRAIN_ENV_FILE=$quoted_env $quoted_train"
tmux new-window -d -t "$TMUX_SESSION" -n gpu-monitor \
  "TRAIN_ENV_FILE=$quoted_env $quoted_monitor"
sleep 2
tmux list-sessions
tmux capture-pane -pt "$TMUX_SESSION:train" -S -40
