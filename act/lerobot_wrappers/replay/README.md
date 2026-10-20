# replay — 녹화 에피소드 재생 검증

녹화된 action을 로봇이 그대로 실행하는지 확인. **ACT 학습 전에 반드시 해볼 것** — 데이터 이상, 그리퍼 매핑 오류, 캘리 실수 등을 조기 발견.

## 사전 준비 (매번)

[settings.md](../../../setup/docs/00_environment_settings.md) "2. 매번 하는 것" — usbipd attach + 포트 확인 (Follower만 있으면 됨, Leader·카메라 불필요).

## 실행

> 터미널 환경: `conda activate lerobot` (A 경로 — ROS 불필요)

```bash
bash replay.sh                          # 기본: omx_garment_pick, episode 0
bash replay.sh omx_garment_pick 3       # episode 3
bash replay.sh omx_bag_open 0
```

- 데이터셋 위치는 기본으로 **레포 안 `data/`** — 다른 곳이면 `export DUARO_DATA_ROOT=/path/to/data`

## 주의 (안전)

- **로봇이 자율로 움직임** — 작업 공간에 손·물건 치우고, 재생 경로를 지켜보며 실행
- **비상 정지 = 전원 차단.** Ctrl+C는 파이썬만 죽이고 모터는 이미 받은 목표 위치까지 계속 움직임
- 첫 재생은 로봇 근처 장애물(기둥·거치대·반대팔)과의 간섭 여부를 특히 주시
- `--robot.port`는 record 때와 같은 포트 확인 (`lerobot-find-port`) — 다른 터미널에서 teleop/record/bringup이 돌고 있으면 안 됨
- Leader arm 불필요 (Follower만 재생)

## 관련 lerobot 소스

- 진입점: `~/lerobot/src/lerobot/replay.py`
- 데이터 로더: `~/lerobot/src/lerobot/datasets/lerobot_dataset.py`
