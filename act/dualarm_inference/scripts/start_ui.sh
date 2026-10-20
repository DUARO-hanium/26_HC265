#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
control_compose up -d zenoh
cyclo_compose up -d cyclo_intelligence
docker_cmd exec "$CYCLO_CONTAINER" /command/s6-rc -u change cyclo_intelligence
printf '%s\n' 'Cyclo Intelligence: http://localhost:7080/ — choose omx_ai_left or omx_ai_right.'
