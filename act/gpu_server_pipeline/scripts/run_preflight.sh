#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
source "$ROS_SETUP"
source "$OMX_WS_SETUP" 2>/dev/null || source /root/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID RMW_IMPLEMENTATION
export PYTHONPATH="$PROJECT_ROOT/src"
exec "$LOCAL_VENV/bin/python" "$PROJECT_ROOT/scripts/preflight_ros.py" "$@"
