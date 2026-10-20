#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
require_running_container
[[ -x "${CAMERA_RECEIVER_SCRIPT:-}" ]] || {
  echo "Set CAMERA_RECEIVER_SCRIPT to your UDP->ROS gscam helper" >&2; exit 2;
}

docker exec "$OMX_CONTAINER" bash -lc '
  mapfile -t pids < <(pgrep -f "[g]scam_node.*__node:=gscam_camera(1|2)" || true)
  ((${#pids[@]} == 0)) || kill -TERM "${pids[@]}"
  for _ in {1..50}; do
    pgrep -f "[g]scam_node.*__node:=gscam_camera(1|2)" >/dev/null || exit 0
    sleep 0.1
  done
  exit 2
'

ROS_DOMAIN_ID="$ROS_DOMAIN_ID" RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  "$CAMERA_RECEIVER_SCRIPT" camera1 "${CAMERA1_PORT:-5000}"
ROS_DOMAIN_ID="$ROS_DOMAIN_ID" RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  "$CAMERA_RECEIVER_SCRIPT" camera2 "${CAMERA2_PORT:-5002}"
echo "Camera receivers started with Fast DDS."
