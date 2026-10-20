#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
require_running_container
require_file "$LOCAL_VENV/bin/python"

mkdir -p "$OMX_SHARED_HOST/runtime"
docker exec "$OMX_CONTAINER" mkdir -p "$OMX_SHARED_CONTAINER"

if [[ ! -x "$OMX_SHARED_HOST/venv/bin/python" ]]; then
  echo "Preparing the LeRobot venv in the existing container workspace mount..."
  if ! cp -al "$LOCAL_VENV" "$OMX_SHARED_HOST/venv" 2>/dev/null; then
    cp -a "$LOCAL_VENV" "$OMX_SHARED_HOST/venv"
  fi
fi

cp -a "$PROJECT_ROOT/src" "$OMX_SHARED_HOST/runtime/"
cp -a "$PROJECT_ROOT/scripts" "$OMX_SHARED_HOST/runtime/"
cp -a "$PROJECT_ROOT/profiles" "$OMX_SHARED_HOST/runtime/"
cp -a "$PROJECT_ROOT/pyproject.toml" "$OMX_SHARED_HOST/runtime/"
mkdir -p "$OMX_SHARED_HOST/runtime/preflight_artifacts"

docker exec "$OMX_CONTAINER" bash -lc "
  source '$ROS_SETUP'
  source '$OMX_WS_SETUP' 2>/dev/null || source /root/ros2_ws/install/setup.bash
  export PYTHONPATH='$OMX_SHARED_CONTAINER/runtime/src'
  '$OMX_SHARED_CONTAINER/venv/bin/python' -c \
    'import lerobot, torch, grpc, lerobot_robot_ros2_omx; assert lerobot.__version__ == \"0.6.0\"; print(\"CONTAINER_RUNTIME_OK\", lerobot.__version__, torch.__version__)'
"
