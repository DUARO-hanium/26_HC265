#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
exec {inference_lock}>"$OMX_ROOT/runtime/inference.lock"
flock -n "$inference_lock" || { echo 'Another standalone inference is running.' >&2; exit 1; }
if [[ ${1:-} == --train-success ]]; then
    shift
    cyclo_compose run --rm --no-deps --entrypoint python lerobot /omx_ws/scripts/train_success.py "$@"
    exit
fi
read_only=false
for argument in "$@"; do
    if [[ $argument == --check || $argument == --help ]]; then read_only=true; fi
done
# Leave ros2_control running; stop the UI policy publisher before taking ownership.
if [[ $read_only == false ]]; then
    nodes=$(ros_exec "$CONTROL_CONTAINER" ros2 node list --no-daemon)
    if [[ $nodes == *'/leader/'* ]]; then
        echo 'Stop the leader teleoperation launch, then start follower-only inference bringup.' >&2
        exit 1
    fi
    cyclo_compose stop lerobot
    control_compose up -d zenoh
fi
cyclo_compose run --rm --no-deps --name omx_ai_act_cli --entrypoint python \
    lerobot /omx_ws/scripts/infer.py "$@"
