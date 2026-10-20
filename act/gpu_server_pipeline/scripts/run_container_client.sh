#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
load_profile_env
require_running_container
[[ -t 0 && -t 1 ]] || { echo "Run from an interactive WSL terminal" >&2; exit 2; }
"$PROJECT_ROOT/scripts/prepare_container_runtime.sh"

docker exec "$OMX_CONTAINER" bash -lc "
  '$OMX_SHARED_CONTAINER/venv/bin/python' - <<'PY'
import grpc
from lerobot.transport import services_pb2, services_pb2_grpc
address = 'host.docker.internal:${LOCAL_POLICY_PORT}'
channel = grpc.insecure_channel(address)
try:
    grpc.channel_ready_future(channel).result(timeout=5)
    services_pb2_grpc.AsyncInferenceStub(channel).Ready(services_pb2.Empty(), timeout=5)
    print('LEROBOT_POLICY_SERVER_READY', address)
finally:
    channel.close()
PY
"

if docker exec "$OMX_CONTAINER" pgrep -f '[l]erobot_robot_ros2_omx.safe_client' >/dev/null; then
  echo "An inference client is already running" >&2; exit 2
fi

env_args=(
  -e LEROBOT_VENV="$OMX_SHARED_CONTAINER/venv"
  -e PYTHONPATH="$OMX_SHARED_CONTAINER/runtime/src"
  -e ROS_DOMAIN_ID="$ROS_DOMAIN_ID"
  -e DRY_RUN="${DRY_RUN:-true}"
  -e TASK_TEXT="${TASK_TEXT:-}"
  -e GRIPPER_HOLD_ENABLED="${GRIPPER_HOLD_ENABLED:-false}"
)
allowlist=(ARM_REAL_HARDWARE MAX_RELATIVE_TARGET MAX_GRIPPER_RELATIVE_TARGET MAX_EXECUTED_ACTIONS
  GRIPPER_CLOSE_ENTER_THRESHOLD_RAD GRIPPER_OPEN_RELEASE_THRESHOLD_RAD GRIPPER_HOLD_TARGET_RAD
  GRIPPER_RELEASE_CONFIRM_ACTIONS ABSOLUTE_ACTION_SATURATION_TOLERANCE_RAD ABSOLUTE_STATE_TOLERANCE_RAD
  STARTUP_FRESHNESS_WAIT_S STARTUP_HEALTH_PROBATION_S JOINT_STALE_TIMEOUT_S JOINT_FAULT_TIMEOUT_S
  CAMERA_STALE_TIMEOUT_S CAMERA_FAULT_TIMEOUT_S MAX_SENSOR_SKEW_S DXL_SOURCE_GAP_TIMEOUT_S
  DXL_ARRIVAL_STALE_TIMEOUT_S DXL_ARRIVAL_FAULT_TIMEOUT_S DXL_LOSS_WINDOW_S WARN_DXL_LOSS_FRACTION
  MAX_DXL_LOSS_FRACTION MIN_DXL_LOSS_SLOTS TRAINING_START_TOLERANCE_RAD ACTIONS_PER_CHUNK
  CHUNK_SIZE_THRESHOLD AGGREGATE_FN QUEUE_EMPTY_GRACE_S FIRST_ACTION_TIMEOUT_S MAX_CHUNK_SILENCE_S
  MAX_REFILL_RTT_S MAX_ACTION_EXECUTION_GAP_S MAX_ACTION_EXECUTION_FAULT_GAP_S FORCE_THRESHOLD_OBSERVATION)
for name in "${allowlist[@]}"; do [[ -v "$name" ]] && env_args+=(-e "$name=${!name}"); done

if [[ "${DRY_RUN:-true}" == "false" ]]; then
  [[ -n "$PROFILE_NAME" ]] || { echo "Real mode requires an audited PROFILE_NAME" >&2; exit 2; }
  profile_container="$(profile_container_dir)"
  for required in safety_limits.audited.json state_limits.audited.json training_start_pose.episode0.json; do
    require_file "$(profile_host_dir)/$required"
  done
  env_args+=(
    -e SAFETY_LIMITS_PATH="$profile_container/safety_limits.audited.json"
    -e STATE_LIMITS_PATH="$profile_container/state_limits.audited.json"
    -e TRAINING_START_POSE_PATH="$profile_container/training_start_pose.episode0.json"
  )
fi

checkpoint="${1:-${REMOTE_CHECKPOINT:-}}"
[[ -n "$checkpoint" ]] || { echo "Set REMOTE_CHECKPOINT in .env" >&2; exit 2; }
mkdir -p "$PROJECT_ROOT/logs"
log_path="${CLIENT_LOG_PATH:-$PROJECT_ROOT/logs/live_client_$(date +%s).log}"
echo "Client log: $log_path"
set +e
docker exec -it "${env_args[@]}" "$OMX_CONTAINER" bash -lc "
  exec '$OMX_SHARED_CONTAINER/runtime/scripts/run_local_client.sh' \"\$1\" host.docker.internal:${LOCAL_POLICY_PORT}
" bash "$checkpoint" 2>&1 | tee "$log_path"
status=${PIPESTATUS[0]}
set -e
exit "$status"
