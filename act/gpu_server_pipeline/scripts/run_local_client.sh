#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env

CHECKPOINT="${1:-${REMOTE_CHECKPOINT:-}}"
SERVER_ADDRESS="${2:-127.0.0.1:${LOCAL_POLICY_PORT}}"
[[ -n "$CHECKPOINT" ]] || { echo "Set REMOTE_CHECKPOINT or pass a checkpoint path" >&2; exit 2; }

DRY_RUN="${DRY_RUN:-true}"
TASK_TEXT="${TASK_TEXT:-Pick a sock from the container and place it on the table}"
VENV="${LEROBOT_VENV:-$LOCAL_VENV}"
EXTRA_ROBOT_ARGS=()

if [[ "$DRY_RUN" == "false" ]]; then
  [[ -t 0 && -t 1 ]] || { echo "Real mode requires an interactive terminal" >&2; exit 2; }
  [[ "${ARM_REAL_HARDWARE:-}" == "I_UNDERSTAND_THIS_MOVES_OMX" ]] || {
    echo "Set ARM_REAL_HARDWARE=I_UNDERSTAND_THIS_MOVES_OMX" >&2; exit 2;
  }
  for required in SAFETY_LIMITS_PATH STATE_LIMITS_PATH TRAINING_START_POSE_PATH; do
    [[ -n "${!required:-}" && -f "${!required}" ]] || {
      echo "$required must point to an audited JSON file" >&2; exit 2;
    }
  done
  echo "REAL OMX CONTROL: topic=/leader/joint_trajectory checkpoint=$CHECKPOINT"
  read -r -p "Type MOVE OMX to continue: " answer
  [[ "$answer" == "MOVE OMX" ]] || exit 2
  EXTRA_ROBOT_ARGS+=(
    --robot.real_hardware_confirmation=I_UNDERSTAND_THIS_MOVES_OMX
    --robot.safety_limits_path="$SAFETY_LIMITS_PATH"
    --robot.state_limits_path="$STATE_LIMITS_PATH"
    --robot.training_start_pose_path="$TRAINING_START_POSE_PATH"
    --robot.training_start_tolerance_rad="${TRAINING_START_TOLERANCE_RAD:-0.08}"
    --robot.max_relative_target="${MAX_RELATIVE_TARGET:-0.05}"
    --robot.max_gripper_relative_target="${MAX_GRIPPER_RELATIVE_TARGET:-0.20}"
    --robot.absolute_action_saturation_tolerance_rad="${ABSOLUTE_ACTION_SATURATION_TOLERANCE_RAD:-0.030680}"
    --robot.absolute_state_tolerance_rad="${ABSOLUTE_STATE_TOLERANCE_RAD:-0.003069}"
  )
fi

# shellcheck disable=SC1090
source "$ROS_SETUP"
if [[ -r "$OMX_WS_SETUP" ]]; then
  # shellcheck disable=SC1090
  source "$OMX_WS_SETUP"
elif [[ -r /root/ros2_ws/install/setup.bash ]]; then
  # shellcheck disable=SC1091
  source /root/ros2_ws/install/setup.bash
fi
export ROS_DOMAIN_ID RMW_IMPLEMENTATION=rmw_fastrtps_cpp

args=(
  --robot.type=ros2_omx
  --robot.id=omx_follower_ros2
  --robot.dry_run="$DRY_RUN"
  --robot.gripper_hold_enabled="${GRIPPER_HOLD_ENABLED:-false}"
  --robot.gripper_close_enter_threshold_rad="${GRIPPER_CLOSE_ENTER_THRESHOLD_RAD:-0.25}"
  --robot.gripper_open_release_threshold_rad="${GRIPPER_OPEN_RELEASE_THRESHOLD_RAD:-0.60}"
  --robot.gripper_hold_target_rad="${GRIPPER_HOLD_TARGET_RAD:-0.13405370712280273}"
  --robot.gripper_release_confirm_actions="${GRIPPER_RELEASE_CONFIRM_ACTIONS:-6}"
  --robot.startup_freshness_wait_s="${STARTUP_FRESHNESS_WAIT_S:-1.0}"
  --robot.startup_health_probation_s="${STARTUP_HEALTH_PROBATION_S:-2.0}"
  --robot.joint_stale_timeout_s="${JOINT_STALE_TIMEOUT_S:-0.15}"
  --robot.joint_fault_timeout_s="${JOINT_FAULT_TIMEOUT_S:-0.50}"
  --robot.camera_stale_timeout_s="${CAMERA_STALE_TIMEOUT_S:-0.30}"
  --robot.camera_fault_timeout_s="${CAMERA_FAULT_TIMEOUT_S:-0.75}"
  --robot.max_sensor_skew_s="${MAX_SENSOR_SKEW_S:-0.20}"
  --robot.dxl_source_gap_timeout_s="${DXL_SOURCE_GAP_TIMEOUT_S:-0.50}"
  --robot.dxl_arrival_stale_timeout_s="${DXL_ARRIVAL_STALE_TIMEOUT_S:-0.12}"
  --robot.dxl_arrival_fault_timeout_s="${DXL_ARRIVAL_FAULT_TIMEOUT_S:-0.50}"
  --robot.dxl_loss_window_s="${DXL_LOSS_WINDOW_S:-5.0}"
  --robot.warn_dxl_loss_fraction="${WARN_DXL_LOSS_FRACTION:-0.10}"
  --robot.max_dxl_loss_fraction="${MAX_DXL_LOSS_FRACTION:-0.20}"
  --robot.min_dxl_loss_slots="${MIN_DXL_LOSS_SLOTS:-120}"
  "${EXTRA_ROBOT_ARGS[@]}"
  --task="$TASK_TEXT"
  --server_address="$SERVER_ADDRESS"
  --policy_type=act
  --pretrained_name_or_path="$CHECKPOINT"
  --policy_device=cuda
  --client_device=cpu
  --fps=30
  --actions_per_chunk="${ACTIONS_PER_CHUNK:-100}"
  --chunk_size_threshold="${CHUNK_SIZE_THRESHOLD:-0.35}"
  --aggregate_fn_name="${AGGREGATE_FN:-weighted_average}"
  --queue_empty_grace_s="${QUEUE_EMPTY_GRACE_S:-0.10}"
  --first_action_timeout_s="${FIRST_ACTION_TIMEOUT_S:-10.0}"
  --max_chunk_silence_s="${MAX_CHUNK_SILENCE_S:-4.0}"
  --max_refill_rtt_s="${MAX_REFILL_RTT_S:-5.0}"
  --max_action_execution_gap_s="${MAX_ACTION_EXECUTION_GAP_S:-0.50}"
  --max_action_execution_fault_gap_s="${MAX_ACTION_EXECUTION_FAULT_GAP_S:-0.50}"
  --force_threshold_observation="${FORCE_THRESHOLD_OBSERVATION:-true}"
)
[[ -z "${MAX_EXECUTED_ACTIONS:-}" ]] || args+=(--max_executed_actions="$MAX_EXECUTED_ACTIONS")

exec "$VENV/bin/python" -m lerobot_robot_ros2_omx.safe_client "${args[@]}"
