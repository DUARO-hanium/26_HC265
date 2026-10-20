#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck disable=SC1091
source "$repo_root/dependencies.lock"

if [[ ! -f .env.local ]]; then
  echo "중단: .env.example을 .env.local로 복사하고 현장 값을 입력하세요." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env.local
set +a

required=(
  CYCLO_DIR OPEN_MANIPULATOR_DIR OPEN_MANIPULATOR_CONTAINER
  ROS_DOMAIN_ID RMW_IMPLEMENTATION FOLLOWER_BY_ID LEADER_BY_ID
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" || "${!name}" == *'<'* ]]; then
    echo "중단: $name 값이 설정되지 않았습니다." >&2
    exit 1
  fi
done

test -d "$CYCLO_DIR/.git" || {
  echo "중단: Cyclo 저장소가 없습니다: $CYCLO_DIR" >&2
  exit 1
}

expected=$CYCLO_COMMIT
observed=$(git -C "$CYCLO_DIR" rev-parse HEAD)
[[ "$observed" == "$expected" ]] || {
  echo "중단: Cyclo 커밋 $observed가 검증된 $expected와 다릅니다." >&2
  exit 1
}

om_expected=$OPEN_MANIPULATOR_COMMIT
test -d "$OPEN_MANIPULATOR_DIR/.git" || {
  echo "중단: OpenManipulator 저장소가 없습니다: $OPEN_MANIPULATOR_DIR" >&2
  exit 1
}
om_observed=$(git -C "$OPEN_MANIPULATOR_DIR" rev-parse HEAD)
[[ "$om_observed" == "$om_expected" ]] || {
  echo "중단: OpenManipulator 커밋이 검증된 버전과 다릅니다." >&2
  exit 1
}

"$repo_root/scripts/wsl/apply_workspace_patches.sh" \
  "$CYCLO_DIR" "$OPEN_MANIPULATOR_DIR" >/dev/null

for role in FOLLOWER_BY_ID LEADER_BY_ID; do
  path="/dev/serial/by-id/${!role}"
  test -e "$path" || {
    echo "중단: $role 장치가 없습니다: $path" >&2
    exit 1
  }
  test -r "$path" && test -w "$path" || {
    echo "중단: 직렬 장치 읽기/쓰기 권한이 부족합니다: $path" >&2
    exit 1
  }
done

follower_path="/dev/serial/by-id/$FOLLOWER_BY_ID"
leader_path="/dev/serial/by-id/$LEADER_BY_ID"
[[ "$(readlink -f "$follower_path")" != "$(readlink -f "$leader_path")" ]] || {
  echo "중단: leader와 follower가 같은 직렬 장치를 가리킵니다." >&2
  exit 1
}

docker info >/dev/null 2>&1 || {
  echo "중단: Docker daemon을 사용할 수 없습니다." >&2
  exit 1
}

zenoh_count=$(
  docker exec "$OPEN_MANIPULATOR_CONTAINER" \
    sh -lc "pgrep -a -x rmw_zenohd 2>/dev/null || true" |
    awk 'NF {count++} END {print count+0}'
)
if (( zenoh_count > 1 )); then
  echo "중단: 로봇 컨테이너 안에 rmw_zenohd가 두 개 이상입니다." >&2
  exit 1
fi

echo "사전 점검 통과(rmw_zenohd 개수: $zenoh_count)."
echo "이 결과만으로 로봇 동작을 시작해서는 안 됩니다."
