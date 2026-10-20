#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
require_running_container
[[ -x "${CAMERA_RECEIVER_SCRIPT:-}" ]] || exit 2

if docker exec "$OMX_CONTAINER" pgrep -f \
  '[l]erobot_robot_ros2_omx.safe_client|[r]os2_control_node|[o]mx_f_follower_ai' >/dev/null; then
  echo "Stop inference and follower bringup before restoring Zenoh." >&2
  exit 2
fi
docker exec "$OMX_CONTAINER" bash -lc '
  mapfile -t pids < <(pgrep -f "[g]scam_node.*__node:=gscam_camera(1|2)" || true)
  ((${#pids[@]} == 0)) || kill -TERM "${pids[@]}"
'
if ! docker exec "$OMX_CONTAINER" pgrep -x rmw_zenohd >/dev/null; then
  docker exec -d "$OMX_CONTAINER" bash -lc "
    source '$ROS_SETUP'; source /root/ros2_ws/install/setup.bash
    export ROS_DOMAIN_ID='$ROS_DOMAIN_ID' RMW_IMPLEMENTATION=rmw_zenoh_cpp
    exec ros2 run rmw_zenoh_cpp rmw_zenohd >/tmp/rmw_zenohd.log 2>&1
  "
fi
ROS_DOMAIN_ID="$ROS_DOMAIN_ID" RMW_IMPLEMENTATION=rmw_zenoh_cpp \
  "$CAMERA_RECEIVER_SCRIPT" camera1 "${CAMERA1_PORT:-5000}"
ROS_DOMAIN_ID="$ROS_DOMAIN_ID" RMW_IMPLEMENTATION=rmw_zenoh_cpp \
  "$CAMERA_RECEIVER_SCRIPT" camera2 "${CAMERA2_PORT:-5002}"
echo "Zenoh collection transport restored."
