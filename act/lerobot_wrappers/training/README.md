# training — ACT 모방학습

수집한 데이터셋(`data/omx_<task>/`)으로 ACT 정책을 학습한다. **NVIDIA GPU 필요.**

## 사전 조건

- `data_collection/`으로 최소 50 에피소드 수집 완료 (ACT 권장치)
- `replay/`로 데이터 이상 여부 검증 완료

## 실행

> 터미널 환경: `conda activate lerobot`

```bash
bash train.sh                       # 기본: omx_garment_pick, 20000 steps
bash train.sh omx_bag_open 50000    # 태스크·스텝 지정
bash train.sh omx_garment_pick 20000 --batch_size=4   # 하이퍼파라미터 추가 (passthrough)
```

## 하이퍼파라미터 조절

**방법 1 (권장): `train.sh` 상단의 변수 수정** — BATCH_SIZE·CHUNK_SIZE·LR 등이 스크립트 안에 기본값으로 정리돼 있어 값만 바꿔서 실행하면 됨.

**방법 2: CLI passthrough** — 3번째 인자부터 `lerobot-train`에 그대로 전달 (⚠️ 스크립트 변수와 같은 옵션을 또 주면 중복 충돌 가능 — 표에 없는 옵션을 쓸 때 활용).

주요 값 (fork 소스에서 확인한 기본값):

| 옵션 | 기본값 | 의미 |
|---|---|---|
| `--batch_size` | 8 | **VRAM 부족(CUDA OOM) 시 제일 먼저 4→2로 줄이기** (RTX 3050 4GB에선 필요할 수 있음) |
| `--steps` | (스크립트 2번째 인자) | 학습 반복 수 |
| `--num_workers` | 4 | 데이터 로딩 프로세스 수 |
| `--save_freq` | 20000 | 체크포인트 저장 주기 |
| `--log_freq` | 200 | 로그 출력 주기 |
| `--policy.chunk_size` | 100 | ACT 행동 청크 길이 (한 번에 예측하는 미래 스텝 수) |
| `--policy.n_action_steps` | 100 | 예측 청크 중 실제 실행할 스텝 수 (≤ chunk_size) |
| `--policy.optimizer_lr` | 1e-5 | 학습률 |
| `--policy.vision_backbone` | resnet18 | 이미지 인코더 |
| `--policy.dim_model` | 512 | 트랜스포머 hidden 차원 |

- 전체 목록: `~/lerobot/src/lerobot/configs/train.py` (학습 공통) + `policies/act/configuration_act.py` (ACT 전용)
- 태스크별 확정값이 생기면 `configs/train_<task>.yaml` 프리셋으로 옮길 예정 (configs/README 참조)

## 결과물

`--output_dir`에 지정된 경로. 기본: `outputs/train/omx_<task>/checkpoints/<step>/` 아래에 체크포인트 저장 (정확한 하위 구조는 첫 학습 후 확인해서 여기 갱신할 것).

**`outputs/`는 `.gitignore` 대상.** 가중치는 별도 백업 위치 사용.

## 자율 실행 (학습된 정책으로 로봇 구동)

> ⚠️ 이 fork(0.3.4)에는 `lerobot-rollout` 명령이 **없음** (pyproject 확인). 실기 추론은 **`lerobot-record` + `--policy.path`** — teleop(Leader) 대신 정책이 Follower를 구동하고, 그 과정이 평가 에피소드로 기록됨.

```bash
lerobot-record \
  --robot.type=omx_follower --robot.port=/dev/ttyACM0 --robot.id=omx_follower_arm \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30}}" \
  --policy.path=outputs/train/omx_garment_pick/checkpoints/last/pretrained_model \
  --dataset.repo_id=duaro/eval_omx_garment_pick \
  --dataset.root=<데이터 루트>/eval_omx_garment_pick \
  --dataset.single_task="Pick up the garment from the table and place it flat" \
  --dataset.num_episodes=3 \
  --dataset.push_to_hub=false
```

- `--teleop.*` 옵션 없음 — 그 자리를 `--policy.path`가 대체
- 카메라 구성은 **학습 데이터와 동일해야 함** (카메라 키 이름·해상도 일치 필수)
- `--policy.path`의 정확한 체크포인트 경로는 학습 후 `outputs/` 구조 보고 지정
- 안전 수칙은 replay와 동일: 비상정지 = 전원 차단, 첫 실행은 작업공간 비우고 주시

## 관련 lerobot 소스

- 진입점: `~/lerobot/src/lerobot/scripts/train.py`
- ACT 모델: `~/lerobot/src/lerobot/policies/act/modeling_act.py`
- ACT 하이퍼파라미터: `~/lerobot/src/lerobot/policies/act/configuration_act.py` (chunk_size 등 기본값)
