#!/usr/bin/env bash
# Save/discard the active episode in the UI before stopping the containers.
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cyclo_compose stop lerobot cyclo_intelligence
control_compose stop
