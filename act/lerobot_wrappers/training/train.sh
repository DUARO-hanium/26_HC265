#!/usr/bin/env bash
# lerobot-train (ACT) 래퍼
# 사용법: bash train.sh [task_name] [steps] [추가 옵션...]
#   추가 옵션은 lerobot-train에 그대로 전달됨. 예:
#   bash train.sh omx_garment_pick 20000 --batch_size=4 --policy.chunk_size=50

set -e

TASK="${1:-omx_garment_pick}"
STEPS="${2:-20000}"
shift $(( $# > 2 ? 2 : $# ))   # 앞 두 인자 소비 — 나머지는 passthrough

# ─── 하이퍼파라미터 (여기서 조절 — 값은 lerobot 소스 기본값과 동일) ───────────
BATCH_SIZE=8            # VRAM 부족(CUDA OOM) 시 4 → 2로 줄이기
NUM_WORKERS=4           # 데이터 로딩 프로세스 수
SAVE_FREQ=20000         # 체크포인트 저장 주기
LOG_FREQ=200            # 로그 출력 주기
CHUNK_SIZE=100          # ACT 행동 청크 길이 (한 번에 예측하는 미래 스텝 수)
N_ACTION_STEPS=100      # 예측 청크 중 실제 실행할 스텝 수 (≤ CHUNK_SIZE)
LR=1e-5                 # 학습률
# ────────────────────────────────────────────────────────────────────────
# ⚠️ 같은 옵션을 passthrough(3번째 인자~)로도 주면 중복 충돌 가능 — 위 변수로 조절 권장

# 데이터셋 위치: 레포 안의 data/ 가 기본값, DUARO_DATA_ROOT 환경변수로 재정의 가능
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${DUARO_DATA_ROOT:-$SCRIPT_DIR/../data}"
DATASET_ROOT="${DATA_ROOT}/${TASK}"

lerobot-train \
  --dataset.repo_id="duaro/${TASK}" \
  --dataset.root="${DATASET_ROOT}" \
  --policy.type=act \
  --output_dir="outputs/train/${TASK}" \
  --policy.device=cuda \
  --steps="${STEPS}" \
  --batch_size="${BATCH_SIZE}" \
  --num_workers="${NUM_WORKERS}" \
  --save_freq="${SAVE_FREQ}" \
  --log_freq="${LOG_FREQ}" \
  --policy.chunk_size="${CHUNK_SIZE}" \
  --policy.n_action_steps="${N_ACTION_STEPS}" \
  --policy.optimizer_lr="${LR}" \
  "$@"
