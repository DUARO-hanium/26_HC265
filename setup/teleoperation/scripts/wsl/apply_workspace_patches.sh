#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck disable=SC1091
source "$repo_root/dependencies.lock"

cyclo_dir=${1:-"${CYCLO_DIR:-$HOME/robot_dependencies/cyclo_intelligence}"}
open_manipulator_dir=${2:-"${OPEN_MANIPULATOR_DIR:-$HOME/robot_dependencies/open_manipulator}"}

verify_checkout() {
  local name=$1
  local directory=$2
  local commit=$3

  test -d "$directory/.git" || {
    echo "중단: $name 저장소가 없습니다: $directory" >&2
    exit 1
  }
  local observed
  observed=$(git -C "$directory" rev-parse HEAD)
  [[ "$observed" == "$commit" ]] || {
    echo "중단: $name HEAD가 검증된 commit과 다릅니다." >&2
    echo "현재: $observed" >&2
    echo "필요: $commit" >&2
    exit 1
  }
}

apply_and_verify() {
  local name=$1
  local directory=$2
  local patch_file=$3
  local expected_files=$4

  if git -C "$directory" apply --reverse --check "$patch_file" 2>/dev/null; then
    echo "$name patch가 이미 적용되어 있습니다."
  elif git -C "$directory" apply --check "$patch_file"; then
    git -C "$directory" apply "$patch_file"
    echo "$name patch를 적용했습니다."
  else
    echo "중단: $name patch를 안전하게 적용할 수 없습니다." >&2
    exit 1
  fi

  git -C "$directory" apply --reverse --check "$patch_file" || {
    echo "중단: $name patch 적용 결과를 검증하지 못했습니다." >&2
    exit 1
  }
  git -C "$directory" diff --check

  if ! cmp -s \
      <(git -C "$directory" diff --no-ext-diff | sed '/^index /d') \
      <(sed '/^index /d' "$patch_file"); then
    echo "중단: $name의 실제 diff가 배포 patch와 정확히 일치하지 않습니다." >&2
    exit 1
  fi

  local actual_files
  actual_files=$(git -C "$directory" diff --name-only | LC_ALL=C sort)
  if [[ "$actual_files" != "$expected_files" ]]; then
    echo "중단: $name에 예상하지 않은 변경 파일이 있습니다." >&2
    echo "$actual_files" >&2
    exit 1
  fi
}

verify_checkout cyclo "$cyclo_dir" "$CYCLO_COMMIT"
verify_checkout \
  open_manipulator "$open_manipulator_dir" "$OPEN_MANIPULATOR_COMMIT"

cyclo_files='shared/shared/robot_configs/omx_f_config.yaml'
open_manipulator_files=$(
  printf '%s\n' \
    open_manipulator_bringup/config/omx_f_follower_ai/hardware_controller_manager.yaml \
    open_manipulator_bringup/config/omx_l_leader_ai/hardware_controller_manager.yaml \
    open_manipulator_bringup/launch/omx_ai.launch.py \
    open_manipulator_bringup/open_manipulator_bringup/joint_trajectory_executor.py |
    LC_ALL=C sort
)

apply_and_verify \
  cyclo "$cyclo_dir" \
  "$repo_root/patches/cyclo/enable_omx_f_camera2.patch" \
  "$cyclo_files"
apply_and_verify \
  open_manipulator "$open_manipulator_dir" \
  "$repo_root/patches/open_manipulator/wsl2_teleoperation.patch" \
  "$open_manipulator_files"

echo "현재 환경용 workspace patch 적용과 검증을 완료했습니다."
