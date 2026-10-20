#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
load_training_env "$@"
prepare_runtime

LOG_FILE="$WORK_ROOT/logs/${JOB_NAME}_gpu_temperature.csv"
WARNING_LOG="$WORK_ROOT/logs/${JOB_NAME}_gpu_temperature_warnings.log"
PID_FILE="$WORK_ROOT/run/${JOB_NAME}.pid"
[[ -s "$LOG_FILE" ]] || printf 'timestamp,gpu_index,temperature_c,utilization_pct,memory_used_mib,power_w\n' > "$LOG_FILE"

for _ in $(seq 1 30); do
  [[ -s "$PID_FILE" ]] && break
  sleep 1
done
[[ -s "$PID_FILE" ]] || { echo "Training PID file did not appear: $PID_FILE" >&2; exit 2; }

while read -r training_pid < "$PID_FILE" && kill -0 "$training_pid" 2>/dev/null; do
  timestamp="$(date --iso-8601=seconds)"
  while IFS=',' read -r index temperature utilization memory power; do
    index="${index// /}"; temperature="${temperature// /}"
    utilization="${utilization// /}"; memory="${memory// /}"; power="${power// /}"
    printf '%s,%s,%s,%s,%s,%s\n' \
      "$timestamp" "$index" "$temperature" "$utilization" "$memory" "$power" >> "$LOG_FILE"
    [[ "$temperature" =~ ^[0-9]+$ ]] || continue
    if (( temperature >= GPU_TEMP_CRITICAL_C )); then
      printf '%s CRITICAL GPU %s temperature %sC\n' "$timestamp" "$index" "$temperature" >> "$WARNING_LOG"
    elif (( temperature >= GPU_TEMP_WARNING_C )); then
      printf '%s WARNING GPU %s temperature %sC\n' "$timestamp" "$index" "$temperature" >> "$WARNING_LOG"
    fi
  done < <(nvidia-smi \
    --query-gpu=index,temperature.gpu,utilization.gpu,memory.used,power.draw \
    --format=csv,noheader,nounits -i "$GPU_IDS")
  sleep "$GPU_MONITOR_INTERVAL_S"
done
