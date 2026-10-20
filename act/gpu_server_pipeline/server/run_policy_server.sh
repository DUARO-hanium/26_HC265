#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SERVER_ENV_FILE:-$ROOT/server/server.env}"
[[ -f "$ENV_FILE" ]] || { echo "Copy server/server.env.example to server/server.env" >&2; exit 2; }
# shellcheck disable=SC1090
source "$ENV_FILE"
GPU="${1:?usage: run_policy_server.sh PHYSICAL_GPU_ID [PORT]}"
PORT="${2:-${POLICY_PORT:-58080}}"
[[ "$GPU" =~ ^[0-9]+$ && "$PORT" =~ ^[0-9]+$ ]] || { echo "GPU and port must be integers" >&2; exit 2; }
[[ -x "$SERVER_VENV/bin/python" ]] || { echo "Run setup_server_env.sh first" >&2; exit 2; }
[[ -d "$CHECKPOINT_PATH" ]] || { echo "Checkpoint not found: $CHECKPOINT_PATH" >&2; exit 2; }
nvidia-smi --query-gpu=index --format=csv,noheader,nounits | grep -qx "$GPU" || { echo "GPU $GPU not found" >&2; exit 2; }
status="$(nvidia-smi -i "$GPU" --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits)"
echo "GPU status: $status"
IFS=',' read -r _ _ temp util used _ <<< "$status"; temp="${temp// /}"; util="${util// /}"; used="${used// /}"
(( temp < ${GPU_TEMP_REFUSE_C:-94} )) || { echo "GPU is too hot (${temp}C)" >&2; exit 2; }
if (( util > 10 || used > 1024 )) && [[ "${ALLOW_BUSY_GPU:-0}" != 1 ]]; then
  echo "GPU appears busy; inspect ownership or set ALLOW_BUSY_GPU=1 deliberately" >&2; exit 2
fi
ss -ltn "sport = :$PORT" | grep -q LISTEN && { echo "Port $PORT is already in use" >&2; exit 2; }
export CUDA_VISIBLE_DEVICES="$GPU"
echo "PolicyServer loopback=${POLICY_HOST:-127.0.0.1}:$PORT physical_gpu=$GPU"
exec "$SERVER_VENV/bin/python" -m lerobot.async_inference.policy_server \
  --host="${POLICY_HOST:-127.0.0.1}" --port="$PORT" --fps="${POLICY_FPS:-30}" \
  --inference_latency=0.033333 --obs_queue_timeout=1.0
