#!/usr/bin/env bash

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OMX_ENV_FILE:-$PROJECT_ROOT/.env}"

load_omx_env() {
  if [[ -f "$ENV_FILE" ]]; then
    # This is a user-owned Bash config. Never source an untrusted .env file.
    # shellcheck disable=SC1090
    source "$ENV_FILE"
  fi
  export PROJECT_ROOT
  export LOCAL_VENV="${LOCAL_VENV:-$PROJECT_ROOT/.venv}"
  export ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
  export OMX_WS_SETUP="${OMX_WS_SETUP:-$HOME/ros2_ws/install/setup.bash}"
  export DOCKER_CONFIG="${DOCKER_CONFIG_DIR:-${DOCKER_CONFIG:-$HOME/.docker}}"
  export OMX_CONTAINER="${OMX_CONTAINER:-open_manipulator}"
  export OMX_CONTAINER_WORKSPACE_HOST="${OMX_CONTAINER_WORKSPACE_HOST:-$HOME/ros2_ws/src/open_manipulator/docker/workspace}"
  export OMX_CONTAINER_WORKSPACE="${OMX_CONTAINER_WORKSPACE:-/workspace}"
  export OMX_SHARED_HOST="$OMX_CONTAINER_WORKSPACE_HOST/.omx_remote_act"
  export OMX_SHARED_CONTAINER="$OMX_CONTAINER_WORKSPACE/.omx_remote_act"
  export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-30}"
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
  export LOCAL_POLICY_PORT="${LOCAL_POLICY_PORT:-58080}"
  export REMOTE_POLICY_PORT="${REMOTE_POLICY_PORT:-58080}"
  export PROFILE_NAME="${PROFILE_NAME:-}"
}

require_file() {
  [[ -f "$1" ]] || { echo "Required file not found: $1" >&2; exit 2; }
}

require_running_container() {
  docker inspect "$OMX_CONTAINER" >/dev/null 2>&1 || {
    echo "Container not found: $OMX_CONTAINER" >&2; exit 2;
  }
  [[ "$(docker inspect -f '{{.State.Running}}' "$OMX_CONTAINER")" == "true" ]] || {
    echo "Container is not running: $OMX_CONTAINER" >&2; exit 2;
  }
}

profile_host_dir() {
  [[ -n "$PROFILE_NAME" ]] || { echo "Set PROFILE_NAME in .env" >&2; exit 2; }
  printf '%s/profiles/%s\n' "$PROJECT_ROOT" "$PROFILE_NAME"
}

profile_container_dir() {
  [[ -n "$PROFILE_NAME" ]] || { echo "Set PROFILE_NAME in .env" >&2; exit 2; }
  printf '%s/runtime/profiles/%s\n' "$OMX_SHARED_CONTAINER" "$PROFILE_NAME"
}

load_profile_env() {
  [[ -n "$PROFILE_NAME" ]] || return 0
  local profile_file="$(profile_host_dir)/profile.env"
  [[ -f "$profile_file" ]] || return 0
  # Profiles are repository/user-owned Bash configuration, never remote input.
  # shellcheck disable=SC1090
  source "$profile_file"
}
