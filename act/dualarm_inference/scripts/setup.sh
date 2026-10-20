#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
python3 "$OMX_ROOT/scripts/bootstrap_sources.py"
python3 "$OMX_ROOT/scripts/generate_config.py"
python3 "$OMX_ROOT/scripts/prepare_cpu_image.py"
control_compose config --quiet
cyclo_compose config --quiet
control_compose pull
if [[ ${1:-} == --rebuild ]] || ! docker_cmd image inspect omx-ai-bimanual/cyclo-intelligence:1.4.0-cpu >/dev/null 2>&1; then
    cyclo_compose build cyclo_intelligence
fi
control_compose up -d
ros_exec "$CONTROL_CONTAINER" bash -c \
    'cd /root/ros2_ws && colcon build --symlink-install --packages-select open_manipulator_description open_manipulator_bringup --cmake-args -DCMAKE_BUILD_TYPE=Release'
cyclo_compose up -d cyclo_intelligence
mkdir -p "$OMX_ROOT/checkpoints/left/pretrained_model" "$OMX_ROOT/checkpoints/right/pretrained_model" \
    "$OMX_ROOT/checkpoints/left_open_success/pretrained_model"
if [[ ${1:-} == --rebuild ]] || ! docker_cmd image inspect omx-ai-bimanual/act:1.4.1-cpu >/dev/null 2>&1; then
    cyclo_compose build lerobot
fi
if [[ ! -f "$OMX_ROOT/cyclo_intelligence/docker/zenoh_cache/common_interfaces/std_msgs/msg/Header.msg" \
      || ! -f "$OMX_ROOT/cyclo_intelligence/docker/zenoh_cache/rcl_interfaces/builtin_interfaces/msg/Time.msg" ]]; then
    mkdir -p "$OMX_ROOT/cyclo_intelligence/docker/zenoh_cache"
    if [[ ! -w "$OMX_ROOT/cyclo_intelligence/docker/zenoh_cache" ]]; then
        docker_cmd run --rm --entrypoint chown \
            -v "$OMX_ROOT/cyclo_intelligence/docker/zenoh_cache:/cache" \
            robotis/open-manipulator:5.1.3 "$(id -u):$(id -g)" /cache
    fi
    bash "$OMX_ROOT/cyclo_intelligence/docker/scripts/init_zenoh_cache.sh"
fi
printf '%s\n' 'Containers prepared; teleoperation has not been started.'
