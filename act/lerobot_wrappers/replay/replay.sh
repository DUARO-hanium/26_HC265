#!/usr/bin/env bash
# lerobot-replay 래퍼
# 사용법: bash replay.sh [task_name] [episode]
#
# 데이터셋 위치: 레포 안의 data/ 가 기본값 (.gitignore 대상이라 커밋 안 됨)
# 다른 위치를 쓰려면 환경변수 DUARO_DATA_ROOT 지정

set -e

TASK="${1:-omx_garment_pick}"
EPISODE="${2:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${DUARO_DATA_ROOT:-$SCRIPT_DIR/../data}"
DATASET_ROOT="${DATA_ROOT}/${TASK}"

if [ ! -d "$DATASET_ROOT" ]; then
    echo "데이터셋 없음: $DATASET_ROOT"
    echo "다른 위치라면: export DUARO_DATA_ROOT=/path/to/data 후 재실행"
    exit 1
fi

lerobot-replay \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=omx_follower_arm \
  --dataset.repo_id="duaro/${TASK}" \
  --dataset.root="${DATASET_ROOT}" \
  --dataset.episode="${EPISODE}"
