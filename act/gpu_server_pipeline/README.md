# LeRobot ACT training + GPU-server inference + ROS 2 OMX control

이 저장소는 두 대의 카메라와 ROBOTIS OpenManipulator-X follower의 실제 joint
state로 LeRobot ACT를 학습하고, 학습한 체크포인트를 원격 NVIDIA GPU 서버에서
실시간 추론한 뒤 ROS 2를 통해 로봇을 구동하는 전체 예제입니다.

핵심 흐름은 다음과 같습니다.

```text
OMX MCAP + two videos
        │
        ▼
official LeRobot 0.6 dataset ──► Accelerate DDP ACT training
                                      │
                                      ▼
Windows cameras ─► WSL ROS 2 ─► SSH/VPN ─► GPU PolicyServer
       follower state ◄──────── action chunks ◄──────┘
              │
              ▼
       OMX follower controller
```

이 구현에서 검증한 작업은 `Pick a sock from the container and place it on the
table`입니다. 코드의 일반 기본값은 **dry-run**이며, 실제 로봇 명령은 별도의
audited profile, 시작 자세 확인, 명시적 환경변수와 `MOVE OMX` 입력 없이는 발행되지
않습니다.

> 중요: 저장소를 clone하는 것만으로 다른 로봇의 물리 안전범위가 자동 보장되지는
> 않습니다. `profiles/in-package-socks`의 수치는 원래 데이터와 로봇에서 얻은
> reference입니다. 다른 OMX에서는 자신의 action/state 범위와 시작 자세를 다시
> 측정·감사한 뒤 사용하세요.

## 포함된 것

- `conversion/`: OMX MCAP + camera MP4/timestamp를 공식 LeRobot v3 형식으로 변환
- `training/`: 공식 `lerobot-train`을 Accelerate DDP로 실행·재개·모니터링
- `server/`: 원격 GPU에서 공식 LeRobot PolicyServer 실행
- `src/lerobot_robot_ros2_omx/`: ROS 2 OMX용 LeRobot Robot adapter
- `scripts/`: local bootstrap, 카메라/Fast DDS, preflight, SSH tunnel, dry/real client
- `profiles/`: 데이터/로봇별 opt-in action/state/start-pose profile
- `tests/`: hardware 없이 실행 가능한 contract와 safety 단위 테스트

데이터셋, 체크포인트, W&B/Hugging Face/GitHub token, 실제 촬영 영상과 로그는 Git에
포함하지 않습니다.

## 0. 검증 환경

- Windows 11 + WSL2 Ubuntu 24.04
- ROS 2 Jazzy
- Docker Desktop + usbipd-win
- ROBOTIS OpenManipulator-X AI follower / OpenRB-150
- camera 2대, 640x480 MJPEG 30 FPS
- LeRobot `0.6.0`, Python 3.12
- 원격 Linux GPU 서버, NVIDIA driver, GPU 1대 이상
- 학습 검증값: RTX A4000 2대, BF16 DDP, global batch 8

다른 하드웨어도 사용할 수 있지만 ROS topic, joint 순서, 카메라 shape, profile을
맞춰야 합니다.

## 1. Clone

```bash
git clone https://github.com/DUARO-hanium/lerobot-ACT-train-inference-GPUserver.git
cd lerobot-ACT-train-inference-GPUserver
```

개인 private mirror를 사용할 권한이 있다면 다음 URL도 같은 commit을 제공합니다.

```bash
git clone https://github.com/YWhero/lerobot-ACT-train-inference-GPUserver.git
```

## 2. 로컬 WSL 환경 준비

먼저 ROS 2 Jazzy와 ROBOTIS OpenManipulator workspace가 동작해야 합니다. Windows
USBIPD와 두 카메라 설치는 [Windows/WSL 설정 가이드](docs/WINDOWS_WSL_SETUP.md)를
따르세요.

```bash
cp .env.example .env
chmod 600 .env
editor .env
```

최소한 다음 값을 자신의 환경으로 바꿉니다.

```text
LOCAL_VENV
OMX_WS_SETUP
OMX_CONTAINER_WORKSPACE_HOST
FOLLOWER_PORT
CAMERA_RECEIVER_SCRIPT
SSH_TARGET
REMOTE_CHECKPOINT
PROFILE_NAME
```

`PROFILE_NAME`은 기본적으로 비어 있어 실제 로봇 모드가 fail-closed합니다. 이 저장소와
동일한 reference 로봇/profile을 감사해서 사용할 때만 다음을 명시합니다.

```bash
PROFILE_NAME="in-package-socks"
cp profiles/in-package-socks/profile.env.example profiles/in-package-socks/profile.env
```

LeRobot 0.6 local environment와 adapter를 설치합니다.

```bash
./scripts/bootstrap_local.sh
./scripts/check_prerequisites.sh
```

## 3. 만들어 둔 LeRobot 데이터셋 사용

Reference 데이터셋은 Hugging Face의 `HYHero/in_package_socks_0805`입니다. 이
데이터셋이 private 상태라면 소유자에게 read access를 받은 뒤 로그인해야 합니다.

```bash
huggingface-cli login
```

GPU 서버에서 학습 설정을 만듭니다.

```bash
cd training
cp training.env.example training.env
chmod 600 training.env
editor training.env
```

접근 권한이 있는 reference 데이터셋을 사용할 때의 핵심 값:

```bash
DATASET_REPO_ID="HYHero/in_package_socks_0805"
DATASET_REVISION="3b301a15253dbdc01c80f6c08a6e30dac93cceca"
DATASET_ROOT="${HOME}/lerobot_act_runtime/data/in_package_socks_0805"
```

Hub에서 snapshot을 먼저 고정해서 받으려면:

```bash
huggingface-cli download HYHero/in_package_socks_0805 \
  --repo-type dataset \
  --revision 3b301a15253dbdc01c80f6c08a6e30dac93cceca \
  --local-dir "${HOME}/lerobot_act_runtime/data/in_package_socks_0805"
```

접근 권한이 없거나 자신의 데이터를 사용하려면 `DATASET_REPO_ID`,
`DATASET_REVISION`, `DATASET_ROOT`만 교체합니다. 필요한 dataset contract는 다음과
같습니다.

```text
fps: 30
observation.images.camera1: video, [480, 640, 3], wrist camera
observation.images.camera2: video, [480, 640, 3], external camera
observation.state: float32[6]
action: float32[6]
joint order: joint1..joint5, gripper_joint_1
```

원본 OMX MCAP을 다시 변환하려면 [데이터 변환 가이드](conversion/README.md)를
따릅니다. 변환기는 짧은 timestamp 역행 pair 제거, 최대 100 ms의 bounded numeric
interpolation, 최대 50 ms의 nearest camera matching을 수행하고 공식 LeRobot 0.6
API가 serialization/video encoding을 담당합니다.

## 4. GPU 서버에서 ACT 학습

저장소를 GPU 서버에도 clone하고 다음을 실행합니다.

```bash
cd lerobot-ACT-train-inference-GPUserver/training
./scripts/setup_training_env.sh
nvidia-smi
./scripts/run_nccl_smoke.sh
```

기본 검증 profile은 GPU 2대, GPU당 batch 4, global batch 8, BF16, 100,000 steps,
2,500-step 평가/체크포인트입니다. `training.env`의 `GPU_IDS`와
`NUM_PROCESSES`를 실제 서버에 맞춥니다.

SSH가 끊겨도 계속 학습하도록 tmux에서 시작합니다.

```bash
./scripts/start_training_tmux.sh
tmux attach -t lerobot_act
```

Detach: `Ctrl+B`, 그다음 `D`.

중단된 공식 체크포인트에서 재개:

```bash
./scripts/resume_act_ddp.sh
```

상세 설정과 W&B key 보관 방식은 [학습 가이드](training/README.md)를 참고하세요.

## 5. 체크포인트 준비

자신의 학습 결과에서는 다음 경로를 사용합니다.

```text
<OUTPUT_DIR>/checkpoints/last/pretrained_model
```

공개된 reference 100k 체크포인트를 비교용으로 내려받을 수도 있습니다.

```bash
huggingface-cli download HYHero/act_in_package_socks_0805_checkpoints \
  --include 'checkpoints/100000/pretrained_model/**' \
  --local-dir "${HOME}/lerobot_act_runtime/reference_checkpoint"
```

다운로드 후 GPU 서버의 `.env` 또는 local client가 전달할
`REMOTE_CHECKPOINT`를 실제 서버 경로로 설정합니다.

## 6. GPU 서버 PolicyServer 실행

GPU 서버에서:

```bash
cd lerobot-ACT-train-inference-GPUserver
cp server/server.env.example server/server.env
chmod 600 server/server.env
editor server/server.env
./server/setup_server_env.sh
./server/run_policy_server.sh 0 58080
```

서버는 기본적으로 `127.0.0.1:58080`에만 bind합니다. 인터넷이나 학교망에 gRPC
port를 직접 공개하지 말고 VPN + SSH tunnel을 사용하세요. 상세 내용은
[원격 inference 가이드](docs/INFERENCE.md)를 참고하세요.

## 7. Windows 카메라와 follower 연결

관리자 PowerShell에서 현재 OpenRB BUSID를 찾아 follower만 WSL에 attach합니다.

```powershell
usbipd list
$followerBusid = 'REPLACE_WITH_CURRENT_BUSID'
usbipd bind --busid $followerBusid       # 최초 Shared가 아닐 때만
usbipd attach --wsl --distribution Ubuntu-24.04-D --busid $followerBusid
```

두 카메라는 Windows에 남겨 두고, camera1=손목/UDP5000,
camera2=외부/UDP5002로 640x480 30 FPS MJPEG를 보냅니다. 동일 모델 카메라는 이름이
같을 수 있으므로 PnP 경로와 실제 화면을 확인해야 합니다. 전체 PowerShell 명령과
노출 `-5`, Auto Off, Low Light Compensation Off 설정은
[Windows/WSL 설정 가이드](docs/WINDOWS_WSL_SETUP.md)에 있습니다.

## 8. WSL inference 준비

```bash
cd lerobot-ACT-train-inference-GPUserver
./scripts/start_existing_container.sh
./scripts/switch_camera_receivers_to_fastdds.sh
./scripts/open_ssh_tunnel.sh
```

Follower health bringup은 토크를 켜지만 자동으로 시작 자세로 움직이지 않습니다.

```bash
./scripts/run_follower_only.sh
```

Prompt:

```text
START FOLLOWER HEALTH CHECK
```

이 터미널은 `Ctrl+C`를 위해 유지합니다. 새 터미널에서 전체 입력을 검사합니다.

```bash
./scripts/run_container_preflight.sh \
  --duration 30 --min-rate 25 \
  --warn-dxl-gap 0.12 \
  --max-dxl-gap 0.50 \
  --max-dxl-loss-fraction 0.20
```

`errors: []`, 두 카메라와 joint/Dynamixel 약 30 Hz, command publisher 0,
controller subscriber 1이어야 합니다.

## 9. 시작 자세와 dry-run

Bundled profile은 original robot의 reference이므로 다른 robot에 바로 적용하지 마세요.
자신의 profile을 감사했다면:

```bash
./scripts/move_to_profile_pose.sh commissioning_start_pose.interior.json
```

Prompt:

```text
MOVE TO PROFILE START
```

먼저 로봇에 명령을 보내지 않는 dry-run을 실행합니다.

```bash
DRY_RUN=true MAX_EXECUTED_ACTIONS=60 ./scripts/run_container_client.sh
```

별도 터미널에서 action을 분석할 수 있습니다.

```bash
./scripts/run_container_dry_run_analyzer.sh 60
```

## 10. 실제 로봇 연속 구동

다음 조건을 모두 만족할 때만 진행합니다.

- 카메라 역할/해상도/30 Hz 확인
- follower joint/Dynamixel preflight 통과
- controller가 `active`
- `/leader/joint_trajectory` 기존 publisher 0
- 자신의 robot/task에서 감사한 action/state/start-pose profile
- 물리 비상정지와 operator 준비
- 로봇 전체 swept volume 비움

총 action 개수 제한 없이 긴 작업을 실행하려면:

```bash
unset MAX_EXECUTED_ACTIONS

DRY_RUN=false \
ARM_REAL_HARDWARE=I_UNDERSTAND_THIS_MOVES_OMX \
TRAINING_START_TOLERANCE_RAD=0.05 \
./scripts/run_container_client.sh
```

마지막 confirmation:

```text
MOVE OMX
```

정지는 client 터미널에서 `Ctrl+C`입니다. 네트워크/센서가 일시적으로 stale이면 과거
action을 interpolation해서 실행하지 않고 새 command 발행을 멈춘 뒤 fresh
observation/chunk로 재동기화합니다.

## 11. 종료

1. inference client `Ctrl+C`
2. follower bringup `Ctrl+C`
3. controller/serial owner가 사라졌는지 확인
4. `./scripts/close_ssh_tunnel.sh`
5. Windows camera sender `Ctrl+C`
6. 필요하면 `docker stop open_manipulator`
7. 모든 software owner와 움직임이 끝난 뒤 robot 전원/USB 분리

기존 Cyclo/Zenoh 데이터 수집으로 돌아갈 때만:

```bash
./scripts/restore_data_collection_zenoh.sh
```

## Safety model

- generic adapter 기본: dry-run, gripper hold off
- real mode: audited action limits + state envelope + start pose 필수
- arm relative step cap과 gripper relative step cap
- DYNAMIXEL rolling source loss/gap, hardware status, camera/joint freshness 감시
- transient gap: HOLD + queue discard + fresh resynchronization
- voltage/temperature/encoder/electrical/overload fault: 즉시 중지
- VPN/SSH remote inference: soft-real-time이며 latency bound 없음

자세한 설계와 제한은 [Safety](docs/SAFETY.md)와
[Architecture](docs/ARCHITECTURE.md)를 읽어 주세요.

## 개발자 테스트

```bash
./scripts/bootstrap_local.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
bash training/tests/test_training_scripts.sh
bash -n scripts/*.sh server/*.sh training/scripts/*.sh
```

## License

Apache-2.0. 외부 프로젝트 attribution은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를
참조하세요.
