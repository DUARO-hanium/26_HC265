#!/usr/bin/env bash
set -euo pipefail
OMX_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export OMX_WS=$OMX_ROOT
export ARCH=amd64
export DISPLAY=${DISPLAY:-}
CONTROL_CONTAINER=omx_ai_bimanual_control
CYCLO_CONTAINER=omx_ai_bimanual_cyclo
mkdir -p "$OMX_ROOT/runtime/control-agent" "$OMX_ROOT/runtime/cyclo-agent"

docker_cmd() {
    if ! command -v docker >/dev/null 2>&1; then
        printf '%s\n' "Install Docker first: bash $OMX_ROOT/scripts/install_host_dependencies.sh" >&2
        return 1
    fi
    if [[ -S /var/run/docker.sock && ! -w /var/run/docker.sock ]]; then
        local docker_command
        printf -v docker_command '%q ' docker "$@"
        sg docker -c "$docker_command"
    else
        docker "$@"
    fi
}

control_compose() {
    docker_cmd compose -p omx_ai_bimanual_control \
        -f "$OMX_ROOT/open_manipulator/docker/docker-compose.yml" \
        -f "$OMX_ROOT/config/control.override.yaml" "$@"
}

cyclo_compose() {
    docker_cmd compose -p omx_ai_bimanual_cyclo \
        -f "$OMX_ROOT/cyclo_intelligence/docker/docker-compose.yml" \
        -f "$OMX_ROOT/config/cyclo.override.yaml" "$@"
}

ros_exec() {
    local container=$1
    shift
    docker_cmd exec -i "$container" bash --noprofile --norc -c \
        'export PATH=/opt/venv/bin:$PATH; export PYTHONPATH=/opt/venv/lib/python3.12/site-packages:${PYTHONPATH:-}; source /opt/ros/jazzy/setup.bash; source /root/ros2_ws/install/setup.bash; exec "$@"' \
        bash "$@"
}

ros_foreground() {
    local container=$1
    shift
    # An attached TTY delivers Ctrl+C to ros2 launch and its child controllers.
    docker_cmd exec -it "$container" bash --noprofile --norc -c \
        'export PATH=/opt/venv/bin:$PATH; export PYTHONPATH=/opt/venv/lib/python3.12/site-packages:${PYTHONPATH:-}; source /opt/ros/jazzy/setup.bash; source /root/ros2_ws/install/setup.bash; exec "$@"' \
        bash "$@"
}
