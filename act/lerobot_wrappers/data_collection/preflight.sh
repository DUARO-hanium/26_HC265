#!/usr/bin/env bash
# 녹화 전 사전 점검 — record.sh가 자동 호출하며 단독 실행도 가능.
# 하나라도 실패하면 exit 1 (녹화 시작 금지). 건너뛰려면 DUARO_SKIP_PREFLIGHT=1.
#
# 점검 항목: 로봇 포트, 카메라 열림, 노출 설정, 저장 위치(ext4/디스크 여유),
# conda 환경, lerobot fork 버전(dependencies.lock 대조).
#
# 사용법:
#   bash preflight.sh [DATA_ROOT] [CAM_FRONT] [CAM_WRIST]
#   인자 생략 시 record.sh와 동일한 기본값/환경변수를 사용한다.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${1:-${DUARO_DATA_ROOT:-$HOME/duaro_data}}"
CAM_FRONT="${2:-${DUARO_CAM_FRONT:-0}}"
CAM_WRIST="${3:-${DUARO_CAM_WRIST:-2}}"

fail=0
warn() { echo "⚠️  $*"; }
ng()   { echo "❌ $*"; fail=1; }
ok()   { echo "✅ $*"; }

# --- 로봇 포트 (by-id 환경변수 우선, 미설정 시 ACM 기본값) ---
if [[ -n "${DUARO_FOLLOWER_BY_ID:-}" && -n "${DUARO_LEADER_BY_ID:-}" ]]; then
    follower_port=$(readlink -f "/dev/serial/by-id/$DUARO_FOLLOWER_BY_ID" 2>/dev/null || true)
    leader_port=$(readlink -f "/dev/serial/by-id/$DUARO_LEADER_BY_ID" 2>/dev/null || true)
    [[ -n "$follower_port" && -e "$follower_port" ]] && ok "follower: $follower_port" \
        || ng "follower by-id 해석 실패: $DUARO_FOLLOWER_BY_ID (usbipd attach 확인)"
    [[ -n "$leader_port" && -e "$leader_port" ]] && ok "leader: $leader_port" \
        || ng "leader by-id 해석 실패: $DUARO_LEADER_BY_ID"
    [[ -n "$follower_port" && "$follower_port" == "$leader_port" ]] \
        && ng "follower/leader가 같은 포트로 해석됨: $follower_port"
else
    warn "by-id 미설정 — ACM 번호로 점검 (재연결 시 leader/follower 뒤바뀜 위험, settings.md 참조)"
    [[ -e /dev/ttyACM0 ]] && ok "/dev/ttyACM0 존재" || ng "/dev/ttyACM0 없음 (usbipd attach 확인)"
    [[ -e /dev/ttyACM1 ]] && ok "/dev/ttyACM1 존재" || ng "/dev/ttyACM1 없음 (usbipd attach 확인)"
fi

# --- 카메라: 장치 존재 + 실제 1프레임 grab ---
check_camera() {
    local name=$1 idx=$2 dev="/dev/video$2"
    if [[ ! -e "$dev" ]]; then
        ng "$name 카메라 장치 없음: $dev (브리지면 setup_v4l2loopback.sh + camera_bridge.sh 실행 확인)"
        return
    fi
    if python - "$idx" <<'EOF' >/dev/null 2>&1
import sys, cv2
cap = cv2.VideoCapture(int(sys.argv[1]), cv2.CAP_V4L2)
ok, _ = cap.read()
cap.release()
sys.exit(0 if ok else 1)
EOF
    then
        ok "$name 카메라($dev) 프레임 수신 확인"
    else
        ng "$name 카메라($dev) 프레임 읽기 실패 (busy/스트림 미수신 — 브리지·송신기 상태 확인)"
    fi
    # 노출: auto_exposure 컨트롤이 있는 실물 카메라만 해당 (loopback 가상 장치는 자동 스킵)
    local exposure
    exposure=$(v4l2-ctl -d "$dev" --get-ctrl auto_exposure 2>/dev/null || true)
    if [[ "$exposure" =~ auto_exposure:\ *3 ]]; then
        warn "$name 카메라 auto exposure 켜짐 — 어두우면 fps 급락. 고정 권장 (settings.md 노출 고정 절차)"
    fi
}
check_camera front "$CAM_FRONT"
check_camera wrist "$CAM_WRIST"

# --- 저장 위치: 9P 경고 + 디스크 여유 ---
case "$DATA_ROOT" in
    /mnt/*) warn "DATA_ROOT가 /mnt/* (9P) — 쓰기 병목으로 녹화 fps가 무너질 수 있음. WSL ext4 권장" ;;
esac
mkdir -p "$DATA_ROOT"
free_gb=$(df -P -BG "$DATA_ROOT" | awk 'NR==2 {gsub("G","",$4); print $4}')
if [[ -n "$free_gb" && "$free_gb" -ge 5 ]]; then
    ok "디스크 여유 ${free_gb}GB (기준 5GB)"
else
    ng "디스크 여유 부족: ${free_gb:-?}GB < 5GB — 녹화 중 가득 차면 데이터 손상"
fi

# --- conda 환경 ---
if [[ "${CONDA_DEFAULT_ENV:-}" == "lerobot" ]]; then
    ok "conda 환경: lerobot"
else
    ng "conda 환경이 lerobot이 아님 (현재: ${CONDA_DEFAULT_ENV:-없음}) — conda activate lerobot"
fi

# --- lerobot fork 버전 (dependencies.lock 대조, 정보성) ---
lock="$SCRIPT_DIR/../dependencies.lock"
if [[ -f "$lock" && -d "$HOME/lerobot/.git" ]]; then
    # shellcheck disable=SC1090
    source "$lock"
    local_commit=$(git -C "$HOME/lerobot" rev-parse HEAD 2>/dev/null || true)
    if [[ "$local_commit" == "${LEROBOT_COMMIT:-}" ]]; then
        ok "lerobot fork가 검증된 commit과 일치"
    else
        warn "lerobot fork commit(${local_commit:0:12})이 dependencies.lock(${LEROBOT_COMMIT:0:12})과 다름 — 문제 발생 시 이 차이부터 의심"
    fi
fi

echo
if (( fail )); then
    echo "preflight 실패 — 위 ❌ 항목 해결 후 재시도 (강제 진행: DUARO_SKIP_PREFLIGHT=1)"
    exit 1
fi
echo "preflight 통과"
