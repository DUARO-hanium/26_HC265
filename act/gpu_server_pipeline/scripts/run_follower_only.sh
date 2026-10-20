#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
require_running_container
[[ -n "${FOLLOWER_PORT:-}" && "$FOLLOWER_PORT" != *REPLACE* ]] || {
  echo "Set FOLLOWER_PORT to your stable /dev/serial/by-id path" >&2; exit 2;
}
[[ -t 0 && -t 1 ]] || { echo "Run from an interactive terminal" >&2; exit 2; }
docker exec "$OMX_CONTAINER" test -r "$FOLLOWER_PORT"
docker exec "$OMX_CONTAINER" test -w "$FOLLOWER_PORT"
if docker exec "$OMX_CONTAINER" pgrep -f \
  '[r]os2_control_node|[o]mx_f_follower_ai|[o]mx_l_leader_ai|[j]oint_trajectory_executor' >/dev/null; then
  echo "A robot bringup already owns the hardware; stop it first." >&2; exit 2
fi
echo "Follower-only bringup enables torque without an automatic pose move."
read -r -p "Clear the workspace, then type START FOLLOWER HEALTH CHECK: " answer
[[ "$answer" == "START FOLLOWER HEALTH CHECK" ]] || exit 2
exec docker exec -it "$OMX_CONTAINER" bash -lc "
  source '$ROS_SETUP'; source /root/ros2_ws/install/setup.bash
  export ROS_DOMAIN_ID='$ROS_DOMAIN_ID' RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  exec ros2 launch open_manipulator_bringup omx_f_follower_ai.launch.py \\
    port_name:='$FOLLOWER_PORT' init_position:=false
"
