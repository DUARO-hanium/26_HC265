#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
side=${1:-both}
exec {camera_lock}>"$OMX_ROOT/runtime/cameras.lock"
flock -n "$camera_lock" || { printf '%s\n' 'Another camera command is running.' >&2; exit 1; }
python3 "$OMX_ROOT/scripts/devices.py" check --cameras-only --side "$side"
control_compose up -d
ros_foreground "$CONTROL_CONTAINER" ros2 launch /omx_ws/launch/cameras.launch.py "side:=$side"
