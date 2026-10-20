#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env

failed=0
for command in docker ssh python3.12; do
  command -v "$command" >/dev/null || { echo "MISSING command: $command"; failed=1; }
done
for file in "$ROS_SETUP" "$OMX_WS_SETUP" "$LOCAL_VENV/bin/python"; do
  [[ -f "$file" ]] || { echo "MISSING file: $file"; failed=1; }
done
if [[ "${FOLLOWER_PORT:-}" == *REPLACE* || -z "${FOLLOWER_PORT:-}" ]]; then
  echo "CONFIGURE FOLLOWER_PORT in .env"
  failed=1
elif [[ ! -e "$FOLLOWER_PORT" ]]; then
  echo "FOLLOWER_PORT is not attached yet: $FOLLOWER_PORT"
fi
if [[ "${CAMERA_RECEIVER_SCRIPT:-}" == *REPLACE* || ! -x "${CAMERA_RECEIVER_SCRIPT:-}" ]]; then
  echo "CONFIGURE executable CAMERA_RECEIVER_SCRIPT in .env"
  failed=1
fi
((failed == 0)) || exit 2
echo "PREREQUISITES_OK"
