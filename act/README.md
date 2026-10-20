# act — 모방학습 기반 듀얼암 패키지 조작

Leader-Follower Teleoperation으로 수집한 실로봇 시연을 학습해 왼팔은 비닐 개구부를 확보·유지하고 오른팔은 내부로 진입해 제품을 인출한다.

| 폴더 | 내용 | 원본 저장소 |
|---|---|---|
| `dualarm_inference/` | OMX-AI 두 대의 팔별 데이터 수집(Cyclo UI)과 **순차 추론** (왼팔 → 성공 판정 → 오른팔). CPU 추론, 성공 분류기 기반 자동 전환 | `dualarm_ACT_inference` (2026-10 최신) |
| `gpu_server_pipeline/` | MCAP → LeRobot v3 변환, Accelerate DDP 학습, 원격 GPU PolicyServer 추론, ROS 2 OMX adapter, 안전 프로파일과 dry-run | `lerobot-ACT-train-inference-GPUserver` |
| `lerobot_wrappers/` | `lerobot-record` / `lerobot-train` / `lerobot-replay` 래퍼와 WSL 카메라 브리지, 데이터셋 검증 | `Robot-Action-Pipeline` |
| `lerobot_fork/` | 팀 fork LeRobot의 upstream 대비 변경분: `omx_follower`, `omx_leader`, usbip 카메라 MJPG 강제, 텔레옵 CSV 로그 | `lerobot` fork |

## 흐름

```
teleoperation (setup/) ─► Episode (MCAP + video)
      │  conversion/convert_dataset.py
      ▼
LeRobot v3 dataset ─► training/train_act_ddp.sh (GPU server)
      │
      ▼
checkpoints/{left,right}/pretrained_model
      │  dualarm_inference/scripts/infer.sh --side sequence
      ▼
왼팔 개구부 확보·유지 ─► 성공 판정 ─► 오른팔 접근·파지·인출
```

## 정책 구성

| | Left Arm | Right Arm |
|---|---|---|
| 역할 | 패키지 파지, 개구부 확보·유지 | 내부 접근, 제품 파지·인출 |
| 정책 | Diffusion Policy | ACT (chunk K=50) |
| 입력 | 고정 RGB + Wrist RGB + joint state (256×256) | 동일 |
| 학습 | AdamW 1e-4, Episode 단위 8:1:1 | 동일 |

데이터 수집 시 패키지 위치, 방향, 개구부 상태, 내부 의류 위치, 방향, 색상을 바꿔 초기조건 암기를 막는다. 실패는 Opening / Insertion / Grasp / Extraction Slip / Incomplete Extraction 으로 분류해 기록한다.

데이터셋, 체크포인트, 토큰은 저장소에 포함하지 않는다.
