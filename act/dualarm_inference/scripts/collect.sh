#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
side=${1:-}
[[ $side == left || $side == right ]] || { echo 'Usage: bash scripts/collect.sh left|right' >&2; exit 2; }
hold_other=false
extra=()
if [[ ${2:-} == --hold-other ]]; then hold_other=true; extra=(--hold-other); fi
exec {teleop_lock}>"$OMX_ROOT/runtime/teleop.lock"
flock -n "$teleop_lock" || { printf '%s\n' 'Another teleoperation command is running.' >&2; exit 1; }
exec {camera_lock}>"$OMX_ROOT/runtime/cameras.lock"
flock -n "$camera_lock" || { printf '%s\n' 'Another camera command is running.' >&2; exit 1; }
python3 "$OMX_ROOT/scripts/devices.py" check --side "$side" "${extra[@]}"
control_compose up -d
ros_exec "$CONTROL_CONTAINER" python3 /omx_ws/scripts/probe_serial.py --side "$side" "${extra[@]}"
bash "$OMX_ROOT/scripts/start_ui.sh"
printf '%s\n' "Choose omx_ai_$side in Cyclo. Selected follower moves to its official initial position."
ros_foreground "$CONTROL_CONTAINER" ros2 launch /omx_ws/launch/collection.launch.py "side:=$side" "hold_other:=$hold_other"
