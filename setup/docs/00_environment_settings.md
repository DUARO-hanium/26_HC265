# settings — 공통 환경 셋팅 가이드

이 레포의 모든 스크립트가 전제하는 환경. 새 컴퓨터 셋업 시 위에서부터 순서대로 진행한다.

## 환경 요약

| 항목 | 값 |
|------|-----|
| OS | Windows 11 + WSL2 (Ubuntu 24.04) |
| Python | 3.10 (conda env `lerobot`) |
| LeRobot | **DUARO 팀 fork** (`lerobot-*` 명령) — ⚠️ `pip install lerobot` 금지, ROBOTIS 원본도 아님 |
| ROS2 | Jazzy |
| 카메라 | Innomaker U20CAM-720P (UVC) |

> 경로별 목적: **모방학습/ACT** = LeRobot만 필요 / **MoveIt·RViz·FK** = ROS2 추가 필요.
> 대부분의 작업은 A만으로 가능. B는 좌표 확인(RViz·tf2_echo)·rule-base 모션에서 사용.

<br>


# 1. 최초 1회 셋팅

## 1.1 Anaconda + conda 환경

```bash
# Anaconda 없으면 설치
wget https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh
bash ./Anaconda3-2024.10-1-Linux-x86_64.sh
source ~/.bashrc

# base 자동 활성화 끄기 (필수 권장 — 켜두면 ROS 터미널에 conda Python이 섞여 충돌 위험)
conda config --set auto_activate_base false

# 가상환경
conda create -y -n lerobot python=3.10
conda activate lerobot

# FFmpeg (svtav1 인코더 필요 — record 영상 인코딩용)
conda install -c conda-forge ffmpeg=6.1.1 -y
ffmpeg -encoders | grep svt      # 결과 없으면: conda install ffmpeg=7.1.1 -c conda-forge
```

## 1.2 LeRobot 설치 

```bash
cd ~        # /mnt/c/... 말고 반드시 WSL 홈에서 (성능·안정성)
git clone https://github.com/DUARO-hanium/lerobot.git
cd lerobot
pip install -e .
pip install -e ".[dynamixel]"    # Dynamixel SDK 포함

# 확인
python -c "import lerobot; print(lerobot.__version__)"
pip show lerobot | grep Editable   # → /home/<사용자>/lerobot 이면 정상
```

> fork에는 패치(카메라 MJPG 강제, `--log_csv`, 그리퍼 캘리 JSON)가 이미 반영되어 있음
> lerobot 내부를 수정할 일이 생기면: `~/lerobot`에서 편집(즉시 반영됨) → 이후 fork에 push

빌드 에러 시:
```bash
sudo apt-get install cmake build-essential python3-dev pkg-config \
  libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
  libswscale-dev libswresample-dev libavfilter-dev
pip install -e .   # 재시도
```

## 1.3 WSL 커널 UVC 빌드 (카메라용, 1회)

WSL2 기본 커널엔 웹캠(UVC) 드라이버가 없어 재빌드 필요. `ls /sys/class/video4linux/`가 에러 없이 되면 이미 완료된 것이니 건너뛰어도 됨

```bash
sudo apt update
sudo apt install -y build-essential flex bison libssl-dev libelf-dev bc dwarves libncurses-dev cpio pahole

cd ~
git clone --depth 1 --branch linux-msft-wsl-5.15.167.4 https://github.com/microsoft/WSL2-Linux-Kernel.git
cd WSL2-Linux-Kernel
cp Microsoft/config-wsl .config

./scripts/config --enable CONFIG_MEDIA_SUPPORT
./scripts/config --enable CONFIG_MEDIA_USB_SUPPORT
./scripts/config --enable CONFIG_MEDIA_CAMERA_SUPPORT
./scripts/config --enable CONFIG_VIDEO_DEV
./scripts/config --enable CONFIG_USB_VIDEO_CLASS
make olddefconfig
grep -E "USB_VIDEO_CLASS|VIDEO_DEV|MEDIA_USB_SUPPORT" .config   # =y 또는 =m 확인

make -j$(nproc)      # 20~40분
cp arch/x86/boot/bzImage /mnt/c/Users/<사용자명>/wsl-uvc-kernel
```

`C:\Users\<사용자명>\.wslconfig` 생성:
```ini
[wsl2]
kernel=C:\\Users\\<사용자명>\\wsl-uvc-kernel
```

적용: (Windows PowerShell) `wsl --shutdown` → WSL 재진입 → `ls /sys/class/video4linux/` 에러 없으면 완료.

## 1.4 usbipd 설치 (Windows, 1회)

```powershell
# 관리자 PowerShell
winget install usbipd
usbipd list                              # BUSID 확인: OpenRB-150 2개("USB Serial Device"), 카메라
usbipd bind --busid <Follower_BUSID>     # bind는 최초 1회만
usbipd bind --busid <Leader_BUSID>
usbipd bind --busid <카메라_BUSID>        # 카메라 개수만큼
```

## 1.5 (B 경로) ROS2 Jazzy + MoveIt + open_manipulator

> RViz로 좌표축 확인, tf2_echo FK 읽기, rule-base 모션에 필요. A(모방학습)만 할 거면 생략.

ROS2 Jazzy는 공식 문서(`ros-jazzy-desktop`)로 설치돼 있다고 가정.

```bash
# ⚠️ colcon 빌드 전 conda 끄기 — conda Python이 ROS 빌드에 섞이면 깨질 수 있음
conda deactivate

sudo apt update
sudo apt install ros-jazzy-moveit ros-jazzy-ros2-control ros-jazzy-ros2-controllers
sudo apt install ros-jazzy-backward-ros ros-jazzy-joint-state-publisher-gui
sudo apt install ros-jazzy-rmw-zenoh-cpp                  # Zenoh RMW (5.0.0 필수)

mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone https://github.com/ROBOTIS-GIT/open_manipulator.git

source /opt/ros/jazzy/setup.bash
cd ~/ros2_ws
colcon build --packages-select \
  open_manipulator_description open_manipulator_moveit_config \
  open_manipulator_bringup open_manipulator_teleop om_spring_actuator_controller
```

- 일부 패키지(om_gravity_compensation_controller 등) 빌드 실패는 무시 가능
- 설치 확인: `ls /opt/ros/` → `jazzy` / 빌드 확인: `ls ~/ros2_ws/install`
- **버전: open_manipulator 5.0.0**
  - 버전 확인: `grep -m1 '<version>' ~/ros2_ws/src/open_manipulator/open_manipulator/package.xml`
  - 이미 4.x로 클론돼 있으면: `cd ~/ros2_ws/src/open_manipulator && git pull` 후 재빌드

### Zenoh 실행 절차 (5.0.0 필수)

```bash
conda deactivate   # (base) 등 conda가 켜져 있으면 끄기
rosenv
ros2 run rmw_zenoh_cpp rmw_zenohd   # 켜둔 채로 두기 — 이게 없으면 ROS 노드끼리 서로를 못 찾음
```

> `zenohd`는 standalone zenoh 설치 시의 명령 — `rmw-zenoh-cpp` 내장 라우터(`ros2 run rmw_zenoh_cpp rmw_zenohd`)를 쓰므로 별도 설치 불필요.

그 다음 다른 터미널들에서 bringup·MoveIt 등 실행 (각각 `rosenv` 먼저)
- GUI(RViz 등): Windows 11 WSLg 기본 지원 — 화면 안 뜨면 `export LIBGL_ALWAYS_SOFTWARE=1` 시도
- 유틸: `sudo apt install v4l-utils` (카메라 진단), `ros-jazzy-usb-cam` (ROS2 카메라 뷰어, 선택)

### ROS 환경 로드 alias 등록 (1회)

ROS2 명령은 터미널마다 `source` 두 줄이 필요, 매번 해야하므로 alias로 등록:

```bash
echo "alias rosenv='source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash && export RMW_IMPLEMENTATION=rmw_zenoh_cpp'" >> ~/.bashrc
source ~/.bashrc
```

> alias에 Zenoh RMW 지정(`RMW_IMPLEMENTATION`)까지 포함 — 5.0.0 기준. 이미 예전 alias를 등록했다면 `~/.bashrc`에서 기존 줄을 지우고 위 줄로 교체.

> ⚠️ `.bashrc`에 source를 **직접**(자동 실행으로) 넣지 말 것 — ROS2와 `conda lerobot`이 둘 다 Python 경로를 건드려서 모든 터미널에 ROS를 자동 로드하면 lerobot 쪽과 충돌할 수 있음

<br>


# 2. 매번 하는 것 (재부팅·USB 재연결 시)

> 성격 구분: `apt install`·`colcon build`·alias 등록 = **1회** / usbipd attach = **재부팅·재연결 시** / `rosenv` = **ROS 쓰는 새 터미널마다** / `ros2 launch`·`lerobot-*` = 설정이 아니라 **그때그때 실행하는 프로그램**.

## 2.1 USB → WSL 연결

```powershell
# Windows PowerShell (관리자)
usbipd attach --wsl --busid <Follower_BUSID>
usbipd attach --wsl --busid <Leader_BUSID>
usbipd attach --wsl --busid <카메라_BUSID>   # ⚠️ 카메라 브리지 사용 시 이 줄은 생략 (카메라는 Windows가 직접 사용)
```

> ⚠️ **usbipd 카메라 경로는 실측 fps가 수 fps로 붕괴하는 문제 확인됨** —
> [data_collection/README.md](data_collection/README.md)의 "카메라 브리지" 우회 경로 권장.
> ⚠️ **장시간 수집 중 노트북 절전 금지** — 절전 진입 시 usbipd attach가 조용히 풀려
> 녹화가 중간에 죽는다. 수집 전 전원 설정에서 절전 해제(또는 `powercfg /change standby-timeout-ac 0`).

## 2.2 WSL에서 장치 확인

```bash
ls /dev/ttyACM*             # Leader/Follower 2개 보여야 함
ls -l /dev/serial/by-id/    # 시리얼 번호로 어느 쪽이 Leader/Follower인지 구분
ls /dev/video*              # 카메라
lerobot-find-port           # 로봇 포트 식별 (케이블 뽑았다 꽂으며)
lerobot-find-cameras opencv # 카메라 인덱스 확인 (캡처 이미지 보고 front/wrist 구분)
```

> ⚠️ 포트(ACM0/1)는 연결 순서에 따라 바뀔 수 있음 — 실행 전 매번 확인 습관.
> ⚠️ usbip는 무압축(YUYV) 고대역폭 스트리밍을 못 넘김 → 카메라는 반드시 **MJPG** (fork에 이미 강제 적용됨).

## 2.3 포트 by-id 고정 (1회 등록, 권장)

ACM 번호 뒤바뀜 사고(leader/follower 반전 → 로봇 오동작)를 원천 차단한다.
`ls -l /dev/serial/by-id/`로 두 장치의 basename을 확인해 `~/.bashrc`에 등록:

```bash
# ~/.bashrc — <...>에 ls -l /dev/serial/by-id/ 출력의 실제 basename을 넣는다
export DUARO_FOLLOWER_BY_ID=<follower의_by-id_basename>
export DUARO_LEADER_BY_ID=<leader의_by-id_basename>
```

등록해두면 record.sh와 preflight.sh가 자동으로 by-id를 사용한다 (미등록 시
기존 ACM 번호로 동작하되 경고 출력). 어느 쪽이 leader/follower인지는 최초 1회
`lerobot-find-port`(케이블 뽑았다 꽂기)로 확정해서 기록할 것.

## 2.4 카메라 노출 고정 (조명 바뀔 때마다)

auto exposure는 어두운 환경에서 노출 시간을 늘리며 **fps를 떨어뜨린다** →
데이터 수집 전 수동 고정 권장. 에피소드 간 밝기 일관성에도 필요.

- **카메라 브리지 사용 시 (권장 경로)** — 카메라가 Windows 소유이므로 Windows에서 설정:
  ```powershell
  # 속성 대화상자를 열어 Exposure 수동 고정 (장치 이름 끝 공백 2칸 주의)
  ffmpeg -hide_banner -f dshow -show_video_device_dialog true -i 'video=Innomaker-U20CAM-720P  ' -t 1 -f null NUL
  ```
  대화상자에서 auto exposure 해제 → 흰색이 날아가지 않고 경계가 선명한 값으로 고정.
  설정 후 대화상자를 닫고 sender를 시작한다. 고정한 값은 현장 메모에 기록.
- **usbipd 경로 사용 시** — WSL에서:
  ```bash
  v4l2-ctl -d /dev/video0 --set-ctrl auto_exposure=1 --set-ctrl exposure_time_absolute=<값>
  ```
  `<값>`은 현장 조명에서 정한 뒤 기록 (preflight.sh가 auto 상태면 경고를 출력한다).

---

# 3. 공통 주의사항

- **LeRobot(teleop/record)과 ROS2 bringup은 같은 포트 동시 사용 불가** — 하나만 실행
- `--robot.id` / `--teleop.id`는 항상 동일하게 유지 (바꾸면 새 캘리브레이션 요구됨)
- 데이터셋·모델 가중치는 커밋 금지 (`.gitignore`에 등록돼 있음)

## Trouble Shooting

| 증상 | 해결 |
|---|---|
| `Missing motor IDs: 11, 12, 13` | 통신/전원 문제 (모터 고장 아님) → 케이블 전부 뽑고 **12V → 5V → USB 순서**로 재연결. baud 1,000,000 유지 |
| 포트 안 보임 | `usbipd attach` 풀렸는지 확인 (2.1) |
| ACM0/1 뒤바뀜 | 2.3의 by-id 등록으로 원천 차단 (임시로는 `lerobot-find-port` 재확인) |
| 카메라 fps 불안정 | record 시 `--dataset.num_image_writer_processes=1` 추가 |
| WSL 자체가 의심될 때 | Windows에서 직접 테스트: `python -m lerobot.teleoperate ... --robot.port=COM3` — 되면 하드웨어 정상, usbipd 문제 |
| `Could not resolve host: github.com` | WSL DNS 고장 → ① `ping -c 2 8.8.8.8` 되면 `echo "nameserver 8.8.8.8" \| sudo tee /etc/resolv.conf` ② ping도 안 되면 PowerShell에서 `wsl --shutdown` 후 재진입 (usbipd attach 다시 필요) |
| colcon 빌드가 이상하게 깨짐 | `(lerobot)` conda가 켜진 채 빌드했는지 확인 → `conda deactivate` 후 재빌드 |
| ros2 노드끼리 서로 못 찾음 (5.0.0) | Zenoh 라우터 안 켰거나 `RMW_IMPLEMENTATION` 미지정 — `rosenv` 후 `ros2 run rmw_zenoh_cpp rmw_zenohd` 먼저 실행 |
| `zenohd: command not found` | standalone zenoh 미설치 상태 — 대신 `ros2 run rmw_zenoh_cpp rmw_zenohd` 사용 |
| ROS 터미널에 `(base)` 표시 | conda base 자동 활성화 → `conda deactivate` + `conda config --set auto_activate_base false` |

<br>

---

<br>

# 참고 — lerobot 명령어 ↔ 소스 코드 매핑

fork(`~/lerobot`)를 수정하거나 동작을 추적할 때 어느 파일을 보면 되는지. 기준 경로: `~/lerobot/src/lerobot/`

| 명령 | 진입 파일 | 같이 보게 되는 핵심 파일 |
|---|---|---|
| `lerobot-find-port` | `find_port.py` | — |
| `lerobot-find-cameras` | `find_cameras.py` | `cameras/opencv/camera_opencv.py` (⚠️ MJPG 패치 파일) |
| `lerobot-calibrate` | `calibrate.py` | `motors/dynamixel/dynamixel.py` (모터 통신), 내장 캘리브레이션 JSON ↓ |
| `lerobot-teleoperate` | `teleoperate.py` (`TeleoperateConfig` — 옵션 정의, ⚠️ `--log_csv` 패치) | `robots/omx_follower/omx_follower.py` (모터 ID·정규화, 55~62행), `teleoperators/omx_leader/omx_leader.py` |
| `lerobot-record` | `record.py` (`RecordConfig`/`DatasetRecordConfig`) | `datasets/lerobot_dataset.py` (저장 구조), `datasets/image_writer.py`, `datasets/video_utils.py` (mp4 인코딩), `cameras/opencv/configuration_opencv.py` (카메라 dict 문법) |
| `lerobot-replay` | `replay.py` | `datasets/lerobot_dataset.py` |
| `lerobot-train` | `scripts/train.py` | `policies/act/modeling_act.py` (ACT 모델 본체), `policies/act/configuration_act.py` (chunk_size 등 기본값), `datasets/factory.py` |
| `lerobot-eval` | `scripts/eval.py` | (시뮬 환경 전용 — 실기 평가는 record + `--policy.path`) |
| 추론(실기) | `record.py` + `--policy.path` | `policies/act/modeling_act.py` 로드해서 teleop 대신 구동 |

**설정·데이터 관련 파일 위치:**

| 무엇 | 위치 |
|---|---|
| 내장 캘리브레이션 JSON (id와 매칭) | `robots/omx_follower/calibration/omx_follower_arm.json`, `teleoperators/omx_leader/calibration/omx_leader_arm.json` |
| OMX 모터 구성 (ID 11~16, 정규화 모드) | `robots/omx_follower/omx_follower.py` 55~62행 |
| 로봇 옵션 기본값 (`--robot.*`) | `robots/omx_follower/config_omx_follower.py` |
| teleop 옵션 기본값 (`--teleop.*`) | `teleoperators/omx_leader/config_omx_leader.py` |
| 데이터셋 경로 규칙·컬럼 스키마 | `datasets/utils.py` |
| action에 실전송값이 저장되는 지점 | `record.py` 273~278행 (`robot.send_action()` 반환값 저장) |
| FK/IK (터치 캘리브레이션 재활용 가능) | `model/kinematics.py` (`RobotKinematics`, placo 기반) |
| 관절 한계 측정 유틸 | `scripts/find_joint_limits.py` |

> 행 번호는 fork 기준 시점의 값 — 업스트림 갱신 시 어긋날 수 있으니 함수명으로 검색 권장.
