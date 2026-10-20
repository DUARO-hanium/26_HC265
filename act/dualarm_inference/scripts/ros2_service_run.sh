#!/usr/bin/env bash
# Preserve this workspace's ROS/Zenoh environment instead of sourcing image .bashrc.
set -e
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-74}
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_zenoh_cpp}
export ROS_DISTRO=${ROS_DISTRO:-jazzy}
export COLCON_WS=${COLCON_WS:-/root/ros2_ws}
export VENV_PATH=${VENV_PATH:-/opt/venv}
export PATH=${VENV_PATH}/bin:${PATH}
export PYTHONPATH=${VENV_PATH}/lib/python3.12/site-packages:${PYTHONPATH:-}
export ZENOH_SHM_ENABLED=true
export ZENOH_TRANSPORT_SHM_ENABLED=true
export S6_VERBOSITY=${S6_VERBOSITY:-1}
ps -o pgid= -p $$ | tr -d ' ' > "/run/${SERVICE_NAME}.pgid"
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "${COLCON_WS}/install/setup.bash"
printf '[%s] ROS domain=%s Zenoh=%s\n' "$SERVICE_NAME" "$ROS_DOMAIN_ID" "$ZENOH_CONFIG_OVERRIDE"
exec bash --noprofile --norc -c "${ROS2_COMMAND}"
