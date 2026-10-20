#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
duration="${1:-60}"
"$PROJECT_ROOT/scripts/prepare_container_runtime.sh"
exec docker exec "$OMX_CONTAINER" bash -lc "
  source '$ROS_SETUP'; source /root/ros2_ws/install/setup.bash
  export ROS_DOMAIN_ID='$ROS_DOMAIN_ID' RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  exec '$OMX_SHARED_CONTAINER/venv/bin/python' \
    '$OMX_SHARED_CONTAINER/runtime/scripts/analyze_dry_run_actions.py' \
    --duration '$duration' \
    --output '$OMX_SHARED_CONTAINER/runtime/preflight_artifacts/dry_run_actions.json'
"
