#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
"$PROJECT_ROOT/scripts/prepare_container_runtime.sh"
exec docker exec "$OMX_CONTAINER" bash -lc "
  export LEROBOT_VENV='$OMX_SHARED_CONTAINER/venv'
  export PYTHONPATH='$OMX_SHARED_CONTAINER/runtime/src'
  export ROS_DOMAIN_ID='$ROS_DOMAIN_ID' RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  source '$ROS_SETUP'; source /root/ros2_ws/install/setup.bash
  exec '$OMX_SHARED_CONTAINER/venv/bin/python' \
    '$OMX_SHARED_CONTAINER/runtime/scripts/preflight_ros.py' \
    --artifacts '$OMX_SHARED_CONTAINER/runtime/preflight_artifacts' \"\$@\"
" bash "$@"
