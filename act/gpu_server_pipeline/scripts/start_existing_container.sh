#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env

if docker inspect "$OMX_CONTAINER" >/dev/null 2>&1; then
  docker start "$OMX_CONTAINER" >/dev/null
  echo "Started existing container: $OMX_CONTAINER"
  exit 0
fi
echo "Container $OMX_CONTAINER does not exist." >&2
echo "Create it first with the official ROBOTIS OpenManipulator Docker instructions." >&2
echo "This script intentionally does not recreate or overwrite a hardware container." >&2
exit 2
