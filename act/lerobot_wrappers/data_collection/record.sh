#!/usr/bin/env bash
# lerobot-record 래퍼
# 사용법: bash record.sh [task_name]
#   task_name 생략 시 default = omx_garment_pick (데이터셋 폴더명과 동일한 전체 이름 사용)
#
# 데이터셋 위치: WSL ext4 홈(~/duaro_data)이 기본값 — /mnt/c에 직접 쓰면
#   9P 파일시스템 오버헤드로 프레임 저장이 느려져 녹화 fps가 무너진다.
#   다른 위치를 쓰려면 환경변수 DUARO_DATA_ROOT 지정.
#   수집이 끝나면 필요 시 Windows 쪽으로 복사한다:
#     cp -r ~/duaro_data/<task> "/mnt/c/Users/kimyo/Desktop/university/2026 hanium/DUARO/data/"
#
# 카메라 인덱스: usbipd 경로는 DUARO_CAM_FRONT=0 DUARO_CAM_WRIST=2 (기본값),
#   v4l2loopback 브리지 사용 시 DUARO_CAM_FRONT=10 DUARO_CAM_WRIST=11 로 지정
#   (브리지 절차는 README "카메라 브리지" 섹션 참조)

set -e

TASK="${1:-omx_garment_pick}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${SCRIPT_DIR}/../configs/record_${TASK}.yaml"

if [ ! -f "$CONFIG" ]; then
    echo "config 없음: $CONFIG"
    echo "사용 가능한 task:"
    ls "${SCRIPT_DIR}/../configs"/record_*.yaml 2>/dev/null | sed 's|.*record_||;s|\.yaml||'
    exit 1
fi

# TODO: YAML을 파싱해 CLI로 전달하거나, 아래 옵션을 config에서 읽도록 개선
# 지금은 하드코드된 예시:

# /mnt/c 기본값 금지 — 9P 쓰기 병목이 녹화 fps를 깎는다 (WSL ext4 사용)
DATA_ROOT="${DUARO_DATA_ROOT:-$HOME/duaro_data}"
DATASET_ROOT="${DATA_ROOT}/${TASK}"

CAM_FRONT="${DUARO_CAM_FRONT:-0}"
CAM_WRIST="${DUARO_CAM_WRIST:-2}"

# 포트: by-id 환경변수 지정 시 고정 식별 (재연결 시 ACM 번호 뒤바뀜 사고 방지,
# 등록법은 settings.md 참조), 미지정 시 기존 ACM 기본값
if [ -n "${DUARO_FOLLOWER_BY_ID:-}" ] && [ -n "${DUARO_LEADER_BY_ID:-}" ]; then
    FOLLOWER_PORT=$(readlink -f "/dev/serial/by-id/$DUARO_FOLLOWER_BY_ID")
    LEADER_PORT=$(readlink -f "/dev/serial/by-id/$DUARO_LEADER_BY_ID")
    # readlink -f는 대상이 없어도 경로를 반환하므로 -e로 실존 확인 필수
    if [ ! -e "$FOLLOWER_PORT" ] || [ ! -e "$LEADER_PORT" ]; then
        echo "by-id 해석 실패 — /dev/serial/by-id/ 와 usbipd attach 확인"; exit 1
    fi
    if [ "$FOLLOWER_PORT" = "$LEADER_PORT" ]; then
        echo "follower/leader가 같은 포트로 해석됨: $FOLLOWER_PORT"; exit 1
    fi
else
    echo "⚠️ by-id 미설정 — ACM 번호 사용 (재연결 시 leader/follower 뒤바뀜 위험)"
    FOLLOWER_PORT=/dev/ttyACM1
    LEADER_PORT=/dev/ttyACM0
fi

# 녹화 전 사전 점검 (건너뛰기: DUARO_SKIP_PREFLIGHT=1)
if [ "${DUARO_SKIP_PREFLIGHT:-0}" != "1" ]; then
    bash "${SCRIPT_DIR}/preflight.sh" "$DATA_ROOT" "$CAM_FRONT" "$CAM_WRIST" \
        || { echo "preflight 실패 — 녹화 중단"; exit 1; }
fi

lerobot-record \
  --robot.type=omx_follower \
  --robot.port="${FOLLOWER_PORT}" \
  --robot.id=omx_follower_arm \
  --robot.cameras="{ front: {type: opencv, index_or_path: ${CAM_FRONT}, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: ${CAM_WRIST}, width: 640, height: 480, fps: 30}}" \
  --teleop.type=omx_leader \
  --teleop.port="${LEADER_PORT}" \
  --teleop.id=omx_leader_arm \
  --display_data=false \
  --dataset.repo_id=duaro/${TASK} \
  --dataset.root="${DATASET_ROOT}" \
  --dataset.single_task="Pick up the garment from the table and place it flat" \
  --dataset.num_episodes=5 \
  --dataset.episode_time_s=100 \
  --dataset.reset_time_s=10 \
  --dataset.push_to_hub=false \
  --resume=true

# 녹화 종료 후 데이터 품질 검증 — FAIL이면 해당 에피소드 재녹화 권장
python "${SCRIPT_DIR}/validate_dataset.py" "$DATASET_ROOT"
