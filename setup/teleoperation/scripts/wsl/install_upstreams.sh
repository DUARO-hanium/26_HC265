#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck disable=SC1091
source "$repo_root/dependencies.lock"

destination=${1:-"$HOME/robot_dependencies"}
mkdir -p "$destination"

install_pinned_repo() {
  local name=$1
  local url=$2
  local commit=$3
  local path="$destination/$name"

  if [[ ! -d "$path/.git" ]]; then
    git clone --recurse-submodules "$url" "$path"
  fi
  git -C "$path" fetch --tags origin
  git -C "$path" checkout --detach "$commit"
  git -C "$path" submodule update --init --recursive
  test "$(git -C "$path" rev-parse HEAD)" = "$commit"
  git -C "$path" status --short
}

install_pinned_repo \
  cyclo_intelligence "$CYCLO_REPOSITORY" "$CYCLO_COMMIT"
install_pinned_repo \
  open_manipulator "$OPEN_MANIPULATOR_REPOSITORY" "$OPEN_MANIPULATOR_COMMIT"

"$repo_root/scripts/wsl/apply_workspace_patches.sh" \
  "$destination/cyclo_intelligence" \
  "$destination/open_manipulator"

echo "고정된 upstream과 현재 환경용 patch를 설치했습니다: $destination"
