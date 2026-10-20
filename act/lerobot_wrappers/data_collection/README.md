# data_collection — Teleoperation 시연 녹화

Leader arm으로 Follower arm을 조종하며 관절값+카메라를 녹화한다. ACT 학습용 데이터셋 생성 단계.

## 사전 준비 (매번)

공통 절차 — **레포 루트 [settings.md](../../../setup/docs/00_environment_settings.md)의 "2. 매번 하는 것"** 수행:
usbipd attach(T0, Windows 관리자 PowerShell) → 장치 확인·포트/카메라 인덱스 식별(T1, WSL `conda activate lerobot`).

> ⚠️ **카메라 경로 선택**: usbipd로 카메라를 attach하는 기존 경로는 실측 fps가
> 수 fps로 붕괴하는 문제가 확인됨 → **아래 "카메라 브리지" 섹션의 우회 경로 권장**
> (그 경우 카메라는 usbipd attach 하지 않고 로봇 팔 2개만 attach).

record 특이사항: `lerobot-find-cameras opencv` 캡처 이미지로 **front/wrist 인덱스를 반드시 구분**해둘 것 — 아래 `--robot.cameras` 옵션에 그대로 들어감 (브리지 사용 시엔 front=10, wrist=11 고정이라 불필요).

## Teleoperation 동작 확인 (record 전 권장)

카메라·녹화 없이 Leader→Follower 미러링만 먼저 확인:

```bash
lerobot-teleoperate \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=omx_follower_arm \
  --teleop.type=omx_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=omx_leader_arm
```

- 관절값이 터미널에 실시간 표시되고 Follower가 Leader를 따라 움직이면 정상
- ⚠️ **id는 매번 동일하게** (`omx_follower_arm`/`omx_leader_arm`) — 바꾸면 새 캘리브레이션 요구됨
- ⚠️ 포트(ACM0/1)는 뺐다 꽂으면 바뀔 수 있음 — `lerobot-find-port`로 매번 확인. record.sh는 `DUARO_FOLLOWER_BY_ID`/`DUARO_LEADER_BY_ID`를 설정해두면 by-id로 고정 식별하므로 이 확인이 불필요해짐 (settings.md 참조). teleop 명령에도 `--robot.port=/dev/serial/by-id/<값>` 형태로 그대로 쓸 수 있음
- (선택) `--log_csv=teleop_log.csv` 붙이면 관절값이 CSV로 저장됨 

## 실행

record.sh가 **preflight(사전 점검) → 녹화 → validate(사후 검증)**를 자동으로 잇는다:
- preflight 실패 시 녹화가 시작되지 않음 (강제 진행: `DUARO_SKIP_PREFLIGHT=1`)
- 종료 후 validate가 에피소드별 PASS/FAIL을 출력 — FAIL 에피소드는 재녹화 권장
- 포트는 `DUARO_FOLLOWER_BY_ID`/`DUARO_LEADER_BY_ID` 설정 시 by-id로 고정 식별 (등록법: settings.md)

```bash
bash record.sh              # 프리셋 사용
```

또는 태스크 지정 (데이터셋 폴더명과 동일한 전체 이름):
```bash
bash record.sh omx_garment_pick
bash record.sh omx_bag_open
```

- 데이터셋 위치는 기본으로 **WSL ext4 홈 `~/duaro_data/`**에 저장 — `/mnt/c`(Windows 드라이브)에 직접 쓰면 9P 파일시스템 병목으로 녹화 fps가 무너지므로 금지. 다른 곳이면 `export DUARO_DATA_ROOT=/path/to/data` (단, ext4 경로만)
- 수집이 끝난 뒤 필요 시 Windows로 복사: `cp -r ~/duaro_data/<task> "/mnt/c/Users/kimyo/Desktop/university/2026 hanium/DUARO/data/"`

## 녹화 중 키보드

| 키 | 동작 |
|---|---|
| → | 현재 에피소드 조기 종료, 다음으로 |
| ← 현재 에피소드 취소하고 재녹화 |
| ESC | 전체 중단 |

## 결과물 위치

`--dataset.root`에 지정된 경로. 기본: `~/duaro_data/<task>/` (WSL ext4)

```
data/<task>/
├── meta/{info.json, episodes.jsonl, tasks.jsonl, stats.json}
├── data/chunk-000/episode_00000N.parquet       # 관절 시계열 (6-dim)
└── videos/chunk-000/observation.images.{front,wrist}/episode_00000N.mp4
```

## 카메라 브리지 (usbipd 우회 — 권장 경로)

**배경:** 카메라를 usbipd로 WSL에 넘기면 USB/IP의 isochronous 전송 한계로 실측
캡처가 수 fps까지 떨어진다 (에피소드 100초 설정에 프레임 31~47개만 저장된
"1분 촬영 → 1초 영상" 증상, 관절값도 같이 언더샘플링되어 학습 불가). usbipd
수준의 해결책은 존재하지 않으므로, 카메라를 Windows에 둔 채 MJPEG를 RTP/UDP로
WSL에 전송해 우회한다. 로봇 팔 시리얼(usbipd)은 기존 그대로 사용한다.

```text
Windows 카메라 ─(MJPEG/RTP/UDP)→ WSL 브리지 ─→ /dev/video10,11(가상) ─→ lerobot-record
windows/start_camera_sender.ps1    camera_bridge.sh   v4l2loopback          무수정
```

**⚠️ 카메라는 usbipd attach 하지 않는다** (Windows가 직접 사용). 로봇 팔 2개만 attach.

### 1회 설치

1. Windows: GStreamer MSVC 배포판 설치 (zenoh 셋업을 했다면 이미 있음 —
   `%LOCALAPPDATA%\Programs\gstreamer` 확인)
2. WSL: `sudo apt-get install -y gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad`
3. WSL: `bash setup_v4l2loopback.sh` — 커스텀 커널 트리(settings.md 1.3의
   `~/WSL2-Linux-Kernel`)에 대고 v4l2loopback 모듈을 빌드·로드

### 매번 실행 순서 (record 전)

```bash
# WSL 재시작 후엔 모듈 재로드부터
bash setup_v4l2loopback.sh

# WSL 터미널 2개: 카메라별 수신 브리지
bash camera_bridge.sh front    # UDP 5000 → /dev/video10
bash camera_bridge.sh wrist    # UDP 5001 → /dev/video11
```

```powershell
# Windows PowerShell 2개: 카메라별 송신 (device-index는 gst-device-monitor-1.0.exe "Video/Source"로 확인)
.\windows\start_camera_sender.ps1 -Source mf -DeviceIndex <front_idx> -WslDistro <배포판명> -Port 5000
.\windows\start_camera_sender.ps1 -Source mf -DeviceIndex <wrist_idx> -WslDistro <배포판명> -Port 5001
```

### 스모크 테스트 (본 수집 전 필수)

```bash
python measure_camera_fps.py 10   # front — PASS(29~31fps) 확인
python measure_camera_fps.py 11   # wrist
```

### record 연결

```bash
export DUARO_CAM_FRONT=10 DUARO_CAM_WRIST=11
bash record.sh <task>
```

### usbipd 경로 진단 (브리지 도입 전 원인 확인용)

```bash
python measure_camera_fps.py 0          # 현재 usbipd 카메라 실측
python measure_camera_fps.py 0 --mjpg   # MJPG 강제 시 차이 → YUYV 협상 문제인지 분리
```

## Trouble Shooting

| 오류 | 해결 |
|---|---|
| `Missing motor IDs: 11, 12, 13` | 케이블 전부 뽑고 **12V → 5V → USB 순서**로 재연결. baud 1,000,000 유지 |
| 포트 안 보임 | `usbipd attach` 풀렸는지 확인 |
| ACM0/1 뒤바뀜 | `lerobot-find-port` 재확인 or `/dev/serial/by-id/`로 구분 |
| fps 불안정 | `--dataset.num_image_writer_processes=1` 추가 |
| 폴더 이미 있음 에러 | `--resume=true`(기본값) 사용. 버릴 데이터라도 `rm -rf` 대신 `mv ~/duaro_data/<task> ~/duaro_data/_failed/<task>_$(date +%m%d_%H%M)` 로 보존 — 실패 원인 분석 자료가 됨 |

## 관련 lerobot 소스

- 진입점: `~/lerobot/src/lerobot/record.py`
- 데이터셋 스키마: `~/lerobot/src/lerobot/datasets/lerobot_dataset.py`
- 카메라 dict 문법: `~/lerobot/src/lerobot/cameras/opencv/configuration_opencv.py`
