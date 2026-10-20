# 시스템 기동 및 10초 테스트 에피소드 수집

이 문서는 OMX-F 데이터 수집 시스템을 안전하게 기동하고, Cyclo UI에서
10초짜리 시험 에피소드 하나를 저장하는 순서를 설명합니다.

이미 다른 노드나 launch 명령이 실행 중인 터미널에는 새 명령을 붙여 넣지
마십시오. 아래 단계마다 별도의 PowerShell 또는 WSL 창을 사용하고,
장시간 실행되는 프로세스는 해당 창의 포그라운드에서 계속 실행해 두십시오.
그러면 어떤 프로세스가 어느 창에서 실행 중인지 확인하기 쉽고, 문제가
생겼을 때 올바른 프로세스만 `Ctrl+C`로 종료할 수 있습니다.

## 시작 전 안전 체크포인트

로봇을 움직일 수 있는 명령을 실행하기 전에 다음 항목을 모두 확인합니다.

- follower 로봇팔의 가동 범위에서 사람, 공구, 케이블과 장애물을 치웁니다.
- 로봇의 외부 전원을 즉시 차단할 수 있는 위치에 손을 둡니다.
- leader와 follower의 USB 장치 및 전원 케이블이 확실히 연결되어 있는지
  확인합니다.
- 모터 LED가 깜박이거나, 전압·하드웨어 오류가 표시되거나, 관절에서
  비정상적인 열 또는 소음이 발생하면 즉시 동작과 녹화를 중단하고 외부
  전원을 끕니다.
- 이 절차는 로봇팔을 임의 자세로 자동 이동시키지 않습니다. teleoperation
  시작 직후 follower가 leader의 현재 자세를 따라 움직일 수 있으므로 두
  로봇의 초기 자세 차이에도 주의합니다.

## 사용할 창

혼동을 피하기 위해 다음과 같이 창을 나누는 것을 권장합니다.

| 창 | 용도 |
|---|---|
| 관리자 PowerShell | OpenRB USB 공유 및 WSL 연결 상태 확인 |
| 카메라 PowerShell 1 | camera1 GStreamer 송신기 |
| 카메라 PowerShell 2 | camera2 GStreamer 송신기 |
| WSL 창 1 | Zenoh daemon |
| WSL 창 2 | camera1 gscam 수신기 |
| WSL 창 3 | camera2 gscam 수신기 |
| WSL 창 4 | Cyclo 컨테이너 및 ROS 서비스 |
| WSL 창 5 | OMX leader/follower teleoperation |
| WSL 창 6 | 토픽 및 녹화 결과 검증 |

장비 구성에 따라 일부 WSL 프로세스가 Cyclo 컨테이너 안에서 실행될 수
있습니다. 이 경우에도 한 창에는 하나의 장시간 실행 프로세스만 두는 원칙을
유지하십시오.

## 1. 관리자 PowerShell — USB 연결

관리자 권한으로 PowerShell을 열고 현재 USB 목록을 확인합니다.

```powershell
usbipd list
```

현재 표시되는 두 OpenRB BUSID를 확인한 뒤 follower와 leader를 WSL에
연결합니다. BUSID는 USB를 다시 꽂으면 바뀔 수 있으므로 이전 실행에서
사용한 값을 그대로 재사용하지 마십시오.

연결 후 `usbipd list`를 다시 실행하여 두 OpenRB 장치가 모두 `Attached`
상태인지 확인합니다. Windows GStreamer가 카메라를 사용해야 하므로
카메라는 WSL에 attach하지 않습니다.

**중단 조건:** OpenRB 두 장치를 명확히 구분할 수 없거나 한 장치라도
`Attached`가 아니면 다음 단계로 넘어가지 않습니다.

## 2. WSL — 사전 점검

새 WSL 창에서 다음 명령을 실행합니다.

```bash
lsusb | grep -i '2f5d:2202'
ls -l /dev/serial/by-id/
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

다음을 확인합니다.

1. 두 OpenRB 장치가 WSL의 USB 목록에 나타납니다.
2. `/dev/serial/by-id/` 아래에서 leader와 follower의 고유 장치 경로를
   확인할 수 있습니다.
3. 필요한 사용자가 두 직렬 장치를 읽고 쓸 수 있습니다.
4. 이전 실행에서 남은 Cyclo, Zenoh, 카메라 수신기 또는 teleoperation
   프로세스가 중복 실행되고 있지 않습니다.

leader/follower 포트에는 `/dev/ttyACM0`처럼 연결 순서에 따라 달라지는
이름을 사용하지 말고 반드시 `/dev/serial/by-id` 경로를 사용합니다.
두 장치의 basename은 설치 단계에서 `.env.local`의 `FOLLOWER_BY_ID`와
`LEADER_BY_ID`에 기록한 값과 일치해야 합니다. 실제 serial을 문서, 명령
기록 또는 Git 추적 파일에 복사하지 않습니다.
Zenoh daemon은 정확히 하나만 실행해야 하며, 각 카메라에는 송신기와
수신기가 각각 하나씩만 있어야 합니다.

저장소 루트에서 제공된 사전 점검 스크립트도 실행합니다.

```bash
bash scripts/wsl/preflight.sh
```

`사전 점검 통과`가 출력되어도 로봇
동작이 자동으로 안전하다는 뜻은 아닙니다. 실제 로봇을 움직이기 전에는
앞의 안전 체크포인트를 다시 확인하십시오.

## 3. 카메라 PowerShell 1·2 — 영상 송신

두 카메라의 노출 상태를 먼저 확인합니다. 자동 노출과 저조도 보정으로
프레임률이 낮아지지 않도록 각 카메라 설정을 점검합니다.

그다음 별도의 PowerShell 창 두 개에서 카메라별 GStreamer 송신기를 하나씩
실행합니다.

카메라 PowerShell 1:

```powershell
$Distro = "<YOUR_WSL_DISTRO>"
$Repo = "\\wsl.localhost\$Distro\home\<USER>\omx-f-zenoh-data-collection"

& "$Repo\scripts\windows\start_camera_sender.ps1" `
  -WslDistro $Distro `
  -DevicePath '<CAMERA1_CURRENT_KS_PATH>' `
  -Port 5000
```

카메라 PowerShell 2:

```powershell
$Distro = "<YOUR_WSL_DISTRO>"
$Repo = "\\wsl.localhost\$Distro\home\<USER>\omx-f-zenoh-data-collection"

& "$Repo\scripts\windows\start_camera_sender.ps1" `
  -WslDistro $Distro `
  -DevicePath '<CAMERA2_CURRENT_KS_PATH>' `
  -Port 5002
```

- camera1: UDP 포트 `5000`
- camera2: UDP 포트 `5002`
- 영상 형식: MJPEG
- 해상도: `640x480`
- 목표 프레임률: `30 Hz`
- 목적지 주소: 현재 WSL IP
- 장치 경로: 현재 Windows 카메라 PnP 경로

카메라 PnP 경로와 WSL IP도 재연결 또는 재부팅 후 바뀔 수 있으므로 매번
현재 값을 사용합니다.

GStreamer가 `PLAYING` 상태를 표시하는 것만으로 실제 30 Hz 송신이
검증되지는 않습니다. 두 PowerShell 창은 그대로 실행해 두고, ROS 수신
토픽의 실측 프레임률은 5단계에서 확인합니다.

**중단 조건:** 카메라가 열리지 않거나, 다른 앱이 카메라를 점유하고 있거나,
파이프라인이 반복해서 중단되면 중복 송신기와 카메라 앱을 정리한 후 다시
시작합니다.

## 4. WSL — Cyclo 및 ROS 구성 요소 기동

각 장시간 프로세스는 별도의 WSL 창에서 실행합니다. 모든 ROS 2
프로세스에는 동일한 환경을 적용해야 합니다.

```bash
export ROS_DOMAIN_ID=30
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
```

다음 순서로 구성 요소를 기동합니다.

1. audited pin으로 checkout한 Cyclo upstream 컨테이너를 시작합니다.
   기존 환경을 불필요하게 제거하지 않도록 `docker compose down`은
   실행하지 않습니다.
2. Zenoh daemon을 하나만 시작합니다.
3. camera1의 UDP `5000` 스트림을 받는 gscam 수신기를 시작합니다.
4. camera2의 UDP `5002` 스트림을 받는 gscam 수신기를 시작합니다.
5. Cyclo orchestrator와 `cyclo_data`를 시작합니다.
6. 기존 upstream OMX teleoperation 구현을 사용하여 leader와 follower를
   기동합니다.

먼저 `.env.local`을 현재 WSL shell에 읽어 들이고 기존 컨테이너를 보존해서
시작합니다.

```bash
cd "$HOME/omx-f-zenoh-data-collection"
set -a
source .env.local
set +a

docker start "$OPEN_MANIPULATOR_CONTAINER" 2>/dev/null || {
  cd "$OPEN_MANIPULATOR_DIR"
  docker compose -f docker/docker-compose.yml \
    up -d --no-build open_manipulator
}

docker start "$CYCLO_CONTAINER" 2>/dev/null || {
  cd "$CYCLO_DIR"
  ARCH=amd64 docker compose -f docker/docker-compose.yml \
    up -d --no-build cyclo_intelligence
}
```

이 container들은 [설치 안내](02_install.md)에 따라 pinned upstream에
`scripts/wsl/apply_workspace_patches.sh`의 local patch를 적용하고 exact diff
검증을 통과한 뒤 빌드한 결과여야 합니다. 검증되지 않은 upstream source에서
즉석으로 다시 빌드하거나 floating `main` 이미지를 섞어 사용하지 않습니다.

로봇 컨테이너 안에 Zenoh daemon이 없을 때만 하나를 시작합니다.

```bash
docker exec "$OPEN_MANIPULATOR_CONTAINER" pgrep -a -x rmw_zenohd || \
docker exec -d "$OPEN_MANIPULATOR_CONTAINER" bash -lc '
  source /opt/ros/jazzy/setup.bash
  source /root/ros2_ws/install/setup.bash
  export ROS_DOMAIN_ID=30
  export RMW_IMPLEMENTATION=rmw_zenoh_cpp
  exec ros2 run rmw_zenoh_cpp rmw_zenohd \
    >/tmp/rmw_zenohd.log 2>&1
'
```

두 gscam 수신기가 이미 실행 중이지 않을 때만 다음을 실행합니다.

```bash
cd "$HOME/omx-f-zenoh-data-collection"
bash scripts/wsl/start_gscam_receiver.sh \
  "$OPEN_MANIPULATOR_CONTAINER" camera1 "$CAMERA1_UDP_PORT"
bash scripts/wsl/start_gscam_receiver.sh \
  "$OPEN_MANIPULATOR_CONTAINER" camera2 "$CAMERA2_UDP_PORT"

docker exec "$OPEN_MANIPULATOR_CONTAINER" pgrep -a -x gscam_node
```

Cyclo의 수집 서비스를 시작합니다.

```bash
curl -fsS -X POST http://localhost:7100/services/orchestrator/start
curl -fsS -X POST http://localhost:7100/services/cyclo_data/start
```

teleoperation은 설치된 OpenManipulator revision의 기존 launch를 사용합니다.
이 launch는 초기 이동을 발생시킬 수 있으므로 `.env.local`의 두 by-id 장치를
다시 확인하고 안전 체크포인트를 통과한 뒤 별도 WSL 창에서 실행합니다.
`/dev/ttyACM*` 번호를 직접 넣지 마십시오.

Teleoperation 전용 WSL 창에서 local 설정을 읽고 두 by-id 경로를 확인합니다.

```bash
cd "$HOME/omx-f-zenoh-data-collection"
set -a
source .env.local
set +a

follower_port="/dev/serial/by-id/$FOLLOWER_BY_ID"
leader_port="/dev/serial/by-id/$LEADER_BY_ID"

test -r "$follower_port" && test -w "$follower_port"
test -r "$leader_port" && test -w "$leader_port"
test "$(readlink -f "$follower_port")" != "$(readlink -f "$leader_port")"
```

하나라도 실패하거나 두 장치가 같은 포트로 해석되면 launch를 실행하지
않습니다. 확인을 통과한 뒤 OpenManipulator container에서 teleoperation을
실행하며 두 포트를 launch argument로 명시적으로 전달합니다.

```bash
docker exec -it \
  -e FOLLOWER_BY_ID="$FOLLOWER_BY_ID" \
  -e LEADER_BY_ID="$LEADER_BY_ID" \
  "$OPEN_MANIPULATOR_CONTAINER" bash -lc '
    source /opt/ros/jazzy/setup.bash
    source /root/ros2_ws/install/setup.bash
    export ROS_DOMAIN_ID=30
    export RMW_IMPLEMENTATION=rmw_zenoh_cpp

    follower_port="/dev/serial/by-id/$FOLLOWER_BY_ID"
    leader_port="/dev/serial/by-id/$LEADER_BY_ID"
    test -e "$follower_port" && test -e "$leader_port"

    exec ros2 launch open_manipulator_bringup \
      omx_ai.launch.py \
      follower_port_name:="$follower_port" \
      leader_port_name:="$leader_port"
  '
```

이 창은 teleoperation이 끝날 때까지 포그라운드로 유지합니다. Launch 직후
follower가 leader의 현재 자세를 따라 움직일 수 있으므로 실행 버튼을 누르기
전에 두 팔의 자세 차이와 충돌 공간을 다시 확인합니다.

teleoperation을 시작하기 직전에 follower 작업 공간이 비어 있고 외부
전원을 즉시 끌 수 있는지 다시 확인합니다. 이 문서의 확인 절차를 건너뛰고
임의의 로봇 자세 명령을 보내지 마십시오.

**중단 조건:** Zenoh daemon이 두 개 이상 보이거나, 직렬 장치 통신 오류,
모터 전압·하드웨어 오류, 중복 ROS 노드 또는 반복적인 프로세스 재시작이
발생하면 녹화를 시작하지 않습니다.

## 5. 녹화 전 토픽과 전송률 검증

검증 전용 WSL 창에서 모든 ROS 프로세스와 같은 환경을 설정한 뒤 각 토픽의
전송률을 측정합니다.

```bash
export ROS_DOMAIN_ID=30
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
timeout 15 ros2 topic hz /camera1/image_raw/compressed
timeout 15 ros2 topic hz /camera2/image_raw/compressed
timeout 10 ros2 topic hz /joint_states
timeout 10 ros2 topic hz /leader/joint_trajectory
timeout 10 ros2 topic hz /tf
```

기대 결과는 다음과 같습니다.

- `/camera1/image_raw/compressed`: 약 `29–31 Hz`
- `/camera2/image_raw/compressed`: 약 `29–31 Hz`
- `/joint_states`: 약 `30 Hz`
- `/leader/joint_trajectory`: 약 `30 Hz`
- `/tf`: 로봇 동작을 추적할 수 있을 만큼 연속적으로 갱신

토픽 이름만 존재하고 메시지가 들어오지 않는 경우도 있으므로 반드시
`ros2 topic hz`의 실제 측정값을 확인합니다. 카메라가 느리거나 로봇 토픽이
누락되거나 심하게 불규칙하면 UI를 열기 전에 원인을 해결합니다.

필요하면 저장소에서 제공하는 토픽 존재 여부 점검도 실행할 수 있습니다.

```bash
bash scripts/wsl/verify_topics.sh
```

이 스크립트의 성공은 토픽이 존재한다는 뜻이며, 위의 전송률 측정을
대체하지 않습니다.

## 6. Cyclo UI — 10초 테스트 에피소드

브라우저에서 다음 주소를 엽니다.

<http://localhost:7080>

UI에서 토픽 목록을 한 번 새로 고친 뒤 두 카메라와 로봇 토픽이 올바르게
선택되었는지 확인합니다. 개인 정보나 실제 작업 정보가 포함되지 않은 시험
task를 준비합니다.

다음 순서로 시험 녹화를 수행합니다.

1. follower 작업 공간과 외부 전원 차단 준비를 마지막으로 확인합니다.
2. UI에서 녹화를 시작합니다.
3. 약 10초 동안만 안전한 teleoperation 데이터를 수집합니다.
4. UI에서 **Stop**을 누릅니다.
5. 이어서 **Finish**를 눌러 에피소드를 확정합니다.
6. 저장 및 transcode가 완전히 끝날 때까지 Cyclo, ROS, 카메라 또는 로봇
   프로세스를 종료하지 않습니다.

저장 중에는 브라우저를 닫거나 컨테이너를 중지하지 마십시오. 완료된 출력은
[`05_data_contract.md`](05_data_contract.md)의 기준으로 검증합니다. 시험
에피소드가 해당 계약을 통과한 뒤에만 실제 데이터 수집을 시작합니다.

다음 중 하나라도 발생하면 시험 에피소드를 정상 데이터로 사용하지
않습니다.

- 한 카메라 영상 또는 로봇 메시지가 누락됨
- MCAP 또는 metadata를 읽을 수 없음
- `.tmp` 파일이나 pending/failed transcode가 남아 있음
- timestamp에 큰 단절이 있음
- 저장 완료 전에 구성 요소가 종료됨

## 7. 안전 종료 순서

종료는 다음 순서를 지킵니다.

1. 진행 중인 에피소드를 UI에서 **Stop** 및 **Finish**하고 저장 완료를
   기다립니다.
2. teleoperation을 중지합니다.
3. 로봇 bringup을 종료하고 로봇 외부 전원을 끕니다.
4. Cyclo orchestrator와 `cyclo_data` 등 Cyclo 서비스를 종료합니다.
5. 두 gscam 카메라 수신기를 종료합니다.
6. 두 Windows GStreamer 송신기를 종료합니다.

`.tmp` 파일이 존재하거나 transcode 작업이 진행 중일 때 프로세스를
강제 종료하지 마십시오. 비정상 종료가 필요했던 에피소드는 실패 증거로
보존하고, 파일 이름이나 metadata를 임의로 고쳐 정상 데이터처럼 만들지
않습니다.
