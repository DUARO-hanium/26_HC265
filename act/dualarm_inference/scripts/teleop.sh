#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
side=${1:-left}
mode=${2:-teleop}
[[ $side == left || $side == right || $side == both ]] || { echo 'Usage: teleop.sh left|right|both [teleop|inference]' >&2; exit 2; }
[[ $mode == teleop || $mode == inference ]] || exit 2
exec {teleop_lock}>"$OMX_ROOT/runtime/teleop.lock"
flock -n "$teleop_lock" || { printf '%s\n' 'Another teleoperation command is running.' >&2; exit 1; }
python3 "$OMX_ROOT/scripts/devices.py" check --serial-only --side "$side" --mode "$mode"
control_compose up -d
ros_exec "$CONTROL_CONTAINER" python3 /omx_ws/scripts/probe_serial.py --side "$side" --mode "$mode"
printf '%s\n' "Starting $side ($mode); homing occurs only in teleop mode."
ros_foreground "$CONTROL_CONTAINER" ros2 launch /omx_ws/launch/teleop.launch.py "side:=$side" "mode:=$mode"
