# 전체 재캘리브레이션 가이드

이 문서는 Windows 11, Ubuntu 24.04 WSL2, ROS 2 Jazzy,
`~/jazzy_ws`를 사용한다는 전제로 작성했다. Codex 없이 아래 창 이름과
명령을 순서대로 따라갈 수 있다.

## 0. 보드와 안전 규칙

이번 시스템에서 사용하는 두 보드는 서로 다른 용도다.

| 보드 | 용도 | 실제 출력 규격 |
|---|---|---|
| Checkerboard | 카메라 내부보정 | 내부 corner `8x6`, 한 square `24 mm` |
| ChArUco | 카메라-로봇 eye-to-hand | `7x5` squares, square `24 mm`, marker `17.28 mm`, `DICT_5X5_100`, 패턴 `168x120 mm` |

Checkerboard의 `8x6`은 사각형 수가 아니라 내부 교차점 수다. 일반적인 완전한
패턴은 9x7 squares이므로 패턴 영역은 약 `216x168 mm`다. 실제 인쇄물의 여러
square를 가로·세로로 재어 24 mm인지 확인한다.

ChArUco는 명목 25/18 mm 보드를 96%로 출력한 결과다. 최대 내부 ChArUco
corner는 `(7-1)*(5-1)=24`개다. A4 종이가 휘지 않도록 평평한 경량 판에
부착하고, 움직이는 gripper finger가 아닌 `end_effector_link`와 함께 움직이는
고정 옆면에 단단히 고정한다. 캘리브레이션 도중 위치가 미끄러지면 전부 다시
해야 한다.

로봇 관련 절대 규칙:

- torque가 켜진 follower를 손으로 강제로 움직이지 않는다.
- 관절 LED 점멸이나 `Hardware Error`, `Input Voltage`, `Overheating`,
  `Overload`, 반복 `no status packet`이 재발하면 calibration과 teleoperation을
  즉시 중단한다. 팔과 ChArUco 판을 안전하게 지지하고 follower 외부 전원을
  끈 뒤, 재launch·반복 전원 투입·reboot·강제 torque-on으로 시험하지 않는다.
  전원이 켜진 상태에서는 DYNAMIXEL 케이블을 분리하지 않는다.
- `omx_ai.launch.py`를 실행하지 않는다. 이 시스템에서는 all-zero 자세를
  포함한 자동 초기 이동이 발생할 수 있다.
- 기존 follower가 실행 중일 때 통합 launch를 중복 실행하지 않는다.
- 팔을 앞으로 끝까지 펴는 자세를 만들지 않는다.
- ChArUco 판의 충돌 반경까지 포함해 작업 공간을 비운다.

## 1. 사용할 창

명령을 섞지 않도록 창 제목을 다음처럼 정한다.

| 창 | 종류 | 계속 실행할 작업 |
|---|---|---|
| PS-A | 관리자 PowerShell | `usbipd` 확인과 robot attach |
| PS-B | 일반 PowerShell | 노출 조정 또는 camera sender |
| WSL-1 | WSL | gscam receiver |
| WSL-2 | WSL | compressed→raw republisher |
| WSL-3 | WSL | follower bringup |
| WSL-4 | WSL | leader launch |
| WSL-5 | WSL | hand-eye node |
| WSL-6 | WSL | debug GUI |
| WSL-7 | WSL | 점검, capture/solve service |

`계속 실행` 창에서는 프롬프트가 돌아오지 않는 것이 정상이다. 다음 명령은 새
창에서 실행한다.

## 2. 최초 1회 설치와 빌드

### WSL-5

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash

sudo apt-get update
sudo apt-get install -y \
  ros-jazzy-camera-calibration \
  ros-jazzy-cv-bridge \
  ros-jazzy-gscam \
  ros-jazzy-image-pipeline \
  ros-jazzy-image-transport \
  ros-jazzy-image-view \
  ros-jazzy-tf2-tools \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad

cd "$HOME/jazzy_ws"
colcon build --symlink-install --packages-select uv_to_world
source "$HOME/jazzy_ws/install/setup.bash"
colcon test --packages-select uv_to_world
colcon test-result --verbose
```

항상 workspace root인 `~/jazzy_ws`에서 빌드한다. 패키지 소스 폴더 안의
`build/`, `install/`, `log/`를 source하지 않는다.

## 3. USB를 다시 꽂은 뒤 역할 확인

### PS-A

```powershell
usbipd list
```

장치 식별값:

- Innomaker camera: `VID:PID 0c45:6367`
- leader/follower OpenRB: `VID:PID 2f5d:2202`

카메라는 Windows GStreamer가 사용한다. `Shared`는 괜찮지만 카메라에
`usbipd attach`를 실행하지 않는다. OpenRB 두 개만, 현재 출력에 나타난 BUSID를
사용해 attach한다. BUSID는 USB를 다시 꽂으면 바뀔 수 있다.

```powershell
usbipd attach --wsl --busid <follower의-현재-BUSID>
usbipd attach --wsl --busid <leader의-현재-BUSID>
usbipd list
```

두 OpenRB가 `Attached`, camera는 `Attached`가 아니어야 한다.

### WSL-5

```bash
lsusb | grep -E '2f5d:2202|0c45:6367'
ls -l /dev/ttyACM* 2>/dev/null
ls -l /dev/serial/by-id/ 2>/dev/null
```

두 장치의 현재 serial-by-id basename을 역할별로 현장 메모에 기록한다.

```text
follower: <FOLLOWER_BY_ID>
leader:   <LEADER_BY_ID>
```

`ttyACM0/1` 번호는 바뀔 수 있으므로 launch에는 by-id를 사용한다. 긴 경로를
직접 줄바꿈해 입력하지 말고 다음처럼 짧게 해석한다.

```bash
follower_port=$(readlink -f /dev/serial/by-id/<FOLLOWER_BY_ID>)
leader_port=$(readlink -f /dev/serial/by-id/<LEADER_BY_ID>)
printf 'follower=%s\nleader=%s\n' "$follower_port" "$leader_port"
test -n "$follower_port" && test -n "$leader_port"
test "$follower_port" != "$leader_port"
```

하나라도 빈 값이거나 두 경로가 같으면 중단한다.

## 4. Windows 카메라 노출 조정

카메라 sender, Windows Camera 앱, 화상회의 앱을 모두 종료한 상태에서 한다.
장치를 동시에 두 프로그램이 열 수 없다.

### PS-B

사용자가 실제로 사용한 명령이다. 장치 이름 끝의 공백 두 칸까지 작은따옴표
안에 포함돼 있다.

```powershell
ffmpeg -hide_banner -f dshow -show_video_device_dialog true -i 'video=Innomaker-U20CAM-720P  ' -t 1 -f null NUL
```

대화상자에서 exposure를 조절해 흰색 영역이 날아가지 않고 검은 marker 경계가
선명하게 보이게 한다. 자동 노출이 pose마다 밝기를 크게 바꾸면 manual exposure를
사용한다. focus/zoom, 해상도, 렌즈를 바꾸면 내부보정을 다시 해야 한다.
대화상자를 닫고 ffmpeg가 종료된 뒤 sender를 시작한다.

## 5. 카메라 index 재확인

USB 재연결 후 Media Foundation index가 바뀔 수 있다. 장치 이름은 숨은 trailing
space 때문에 선택 실패 이력이 있으므로 index를 사용한다.

### PS-B

```powershell
$gstDir = "$env:LOCALAPPDATA\Programs\gstreamer\1.0\msvc_x86_64\bin"
& "$gstDir\gst-device-monitor-1.0.exe" "Video/Source"
```

`Innomaker-U20CAM-720P`가 열거되는 순서를 확인한다. 현재 검증된 값은
zero-based `device-index=1`이지만 재연결 후 매번 다시 확인한다.

선택한 index의 기본 open 시험:

```powershell
& "$gstDir\gst-launch-1.0.exe" -v `
  mfvideosrc device-index=1 num-buffers=30 `
  ! fakesink sync=false

$LASTEXITCODE
```

`0`이어야 한다. MJPEG 1280x720 30Hz 시험:

```powershell
& "$gstDir\gst-launch-1.0.exe" -v `
  mfvideosrc device-index=1 num-buffers=300 `
  ! 'image/jpeg,width=1280,height=720,framerate=30/1' `
  ! rtpjpegpay pt=26 mtu=1400 `
  ! fakesink sync=false

$LASTEXITCODE
```

이 카메라는 MF MJPEG 뒤에 `jpegparse`를 넣으면 stream error가 발생했다.
MF 경로에는 넣지 않는다.

## 6. Windows→WSL 영상 전송

### WSL-1: 먼저 receiver

내부보정 전이라 `camera1.yaml`이 없으면 calibration file warning은 예상된다.

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash

"$HOME/jazzy_ws/src/uv_to_world/scripts/linux/start_gscam_receiver.sh" \
  5000 camera1
```

### PS-B: sender

UNC script는 서명되지 않았으므로 현재 PowerShell 프로세스에만 Bypass를 건다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$Distro = "<YOUR_WSL_DISTRO>"
$User = "<YOUR_WSL_USER>"
$script = "\\wsl.localhost\$Distro\home\$User\jazzy_ws\src\uv_to_world\scripts\windows\start_camera_sender.ps1"

& $script `
  -Source mf `
  -DeviceIndex 1 `
  -WslDistro $Distro `
  -Width 1280 `
  -Height 720 `
  -Fps 30 `
  -Port 5000
```

### WSL-2: raw republisher

다음 Bash 배열을 그대로 사용한다. 긴 parameter 이름 중간에서 줄을 자르지 않는다.

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash

topic=/camera1/image_raw
in_qos="qos_overrides.${topic}/compressed.subscription.reliability"
out_qos="qos_overrides.${topic}.publisher.reliability"

ros_args=(--ros-args)
ros_args+=(-p in_transport:=compressed)
ros_args+=(-p out_transport:=raw)
ros_args+=(-p "${in_qos}:=best_effort")
ros_args+=(-p "${out_qos}:=best_effort")
ros_args+=(-r "in/compressed:=${topic}/compressed")
ros_args+=(-r "out:=${topic}")

ros2 run image_transport republish "${ros_args[@]}"
```

### WSL-5: 확인

```bash
source /opt/ros/jazzy/setup.bash

timeout 10 ros2 topic echo \
  /camera1/image_raw/compressed --once --no-arr

timeout 10 ros2 topic echo \
  /camera1/image_raw --once --no-arr

timeout 15 ros2 topic hz \
  /camera1/image_raw/compressed --window 300
```

compressed는 약 30Hz가 정상이다. raw는 JPEG decode와 WSL CPU 부하로 더 낮을
수 있다. `image_transport`는 lazy이므로 raw subscriber가 없을 때 compressed
subscription이 잠시 0으로 보일 수 있다.

## 7. Checkerboard 카메라 내부보정

Checkerboard만 사용한다. ChArUco는 아직 사용하지 않는다. 최종 사용 상태인
1280x720, 고정 focus/zoom/exposure로 진행한다.

### WSL-5

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash

calib_args=(
  --pattern chessboard
  --size 8x6
  --square 0.024
  --camera_name camera1
  --queue-size 1
  --no-service-check
  --ros-args
  -r image:=/camera1/image_raw
)

ros2 run camera_calibration cameracalibrator \
  "${calib_args[@]}"
```

보드는 평평하게 유지한다. 카메라를 최종 설치 위치에 고정한 채 보드를 움직이는
방식이 가장 편하다. 다음 구성을 골고루 모은다.

- 영상 중앙, 좌상/우상/좌하/우하 가장자리
- 가까운 거리, 중간 거리, 먼 거리
- 정면뿐 아니라 좌우·상하 기울기와 roll
- 보드 전체가 영상 안에 있고 모든 내부 corner가 선명한 프레임

같은 정면 pose를 반복하거나 보드가 움직이는 중인 흐린 프레임은 피한다.
GUI 진행 막대가 충분히 채워지면 `CALIBRATE`, 직선 확인 후 `SAVE`한다.

SAVE는 `/tmp/calibrationdata.tar.gz`를 덮어쓴다. 즉시 보관한다.

```bash
stamp=$(date +%Y%m%d_%H%M%S)
session="$HOME/.ros/uv_to_world/sessions/intrinsic_$stamp"
mkdir -p "$session"
tar -xzf /tmp/calibrationdata.tar.gz -C "$session"
find "$session" -maxdepth 1 -name 'left-*.png' | wc -l
sed -n '1,120p' "$session/ost.yaml"
```

`image_width: 1280`, `image_height: 720`, `camera_name: camera1`,
`distortion_model: plumb_bob`, K의 fx/fy가 0이 아닌지 확인한다.

새 결과 bundle을 만든다.

```bash
profile="camera1_$(date +%Y%m%d_%H%M%S)"
bundle="$HOME/.ros/uv_to_world/calibrations/$profile"
mkdir -p "$bundle/reports"
cp "$session/ost.yaml" "$bundle/camera_intrinsics.yaml"
cp "$session/ost.txt" "$bundle/reports/intrinsic_ost.txt"
printf 'bundle=%s\n' "$bundle"
```

현재 receiver 기본 경로에도 설치한다.

```bash
mkdir -p "$HOME/.ros/camera_info"
cp "$bundle/camera_intrinsics.yaml" "$HOME/.ros/camera_info/camera1.yaml"
```

WSL-1 receiver를 `Ctrl+C` 후 다시 시작해 calibration이 load되는지 확인한다.

## 8. Rectification 확인

CameraInfo YAML을 load한 것만으로 영상이 rectified되는 것은 아니다.

### WSL-5

```bash
source /opt/ros/jazzy/setup.bash

rectify_args=(
  --ros-args
  -p queue_size:=1
  -r image:=/camera1/image_raw
  -r camera_info:=/camera1/camera_info
  -r image_rect:=/camera1/image_rect
)

ros2 run image_proc rectify_node "${rectify_args[@]}"
```

다른 WSL 창:

```bash
timeout 10 ros2 topic echo \
  /camera1/image_rect --once --no-arr

ros2 run image_view image_view --ros-args \
  -r image:=/camera1/image_rect
```

1280x720 `bgr8`, 직선이 곧게 보이는지 확인한다. hand-eye는 raw image와 K,D를
직접 사용하므로 이 확인 후 rectify node를 종료해도 된다.

## 9. Follower 로봇과 TF

OpenRB 외부 전원을 확인한다. follower 전원이 빠져 있으면 Input Voltage Error와
일부 ID no status packet이 발생한다.

### WSL-3

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash
source "$HOME/jazzy_ws/install/setup.bash"

follower_port=$(readlink -f /dev/serial/by-id/<FOLLOWER_BY_ID>)
test -n "$follower_port" || { echo 'STOP: follower not found'; return 1; }

ros2 launch open_manipulator_bringup \
  omx_f_follower_ai.launch.py \
  port_name:="$follower_port" \
  start_rviz:=false \
  init_position:=false
```

정상 로그는 ID 11–16 ping, hardware active, torque ON,
`arm_controller`와 `joint_state_broadcaster` active다. torque ON 이후 follower를
손으로 움직이지 않는다.

### WSL-5

```bash
ros2 control list_controllers
ros2 topic list | grep -E '^/joint_states$|^/tf$|^/tf_static$'
timeout 10 ros2 run tf2_ros tf2_echo link0 end_effector_link
```

실제 TF는 `world→link0→link1→...→link5→end_effector_link`다.

## 10. 기존 ROBOTIS leader teleoperation 시작

현재 절차는 follower를 이미 `init_position:=false`로 실행했으므로 통합
`omx_ai.launch.py`를 중복 실행하지 않는다. 워크스페이스에 기존 제공된 standalone
leader launch를 사용한다. 시작 즉시 현재 leader pose가 follower에 전달되므로
두 팔 주변을 비우고 leader와 follower를 가능한 비슷한 안전 자세로 놓는다.
leader gripper도 초기화될 수 있으므로 손을 치운다.

### WSL-4

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash
source "$HOME/jazzy_ws/install/setup.bash"

leader_port=$(readlink -f /dev/serial/by-id/<LEADER_BY_ID>)
printf 'leader_port=%s\n' "$leader_port"
test -n "$leader_port" || { echo 'STOP: leader not found'; return 1; }

ros2 launch open_manipulator_bringup \
  omx_l_leader_ai.launch.py \
  port_name:="$leader_port"
```

긴 by-id를 `...-`와 `if00`으로 나눠 입력하면 `if00: command not found`가
발생한다. 위 wildcard/readlink 방식을 사용한다.

정상적으로 시작되면 leader를 천천히 움직였을 때 follower가 추종한다. follower는
직접 손으로 움직이지 않는다. ChArUco는 고정 옆면에 부착한 상태를 유지하며,
gripper를 움직여 보드 장착 상태가 바뀌지 않게 한다. 비상시에는 leader를 놓고
follower 외부 전원을 차단한다.

## 11. ChArUco eye-to-hand

ChArUco를 end-effector 고정 옆면에 부착하고 영상에서 가능하면 18–24 corners가
고르게 보이도록 한다. 한두 marker가 가려지는 것은 가능하지만 한쪽 corner만
몰리거나 반사·휨이 있으면 사용하지 않는다.

> **Hand-eye 노드는 정확히 하나만 실행한다.** 첫 capture 이후에는 build,
> launch 반복, 노드 재시작 또는 reset을 하지 않는다. 반복하는 것은 launch가
> 아니라 capture 서비스 호출이다. 모든 sample은 solve 전까지 노드 RAM에만
> 존재한다.

### WSL-5: hand-eye node

```bash
cd "$HOME/jazzy_ws"
source /opt/ros/jazzy/setup.bash
source "$HOME/jazzy_ws/install/setup.bash"

if ros2 node list --no-daemon | grep -qx '/handeye_calibrator'; then
  echo 'HAND-EYE ALREADY RUNNING: do not launch again'
else
  ros2 launch uv_to_world handeye_calibration.launch.py
fi
```

빌드가 필요하면 어떤 sample도 수집하기 전에 §2에서 완료한다. 이미 node가
실행 중이면 이 창에서 새 launch를 시작하지 않고 기존 hand-eye 창을 유지한다.

### WSL-6: debug GUI

```bash
ros2 run image_view image_view --ros-args \
  -p 'qos_overrides./camera1/handeye/debug_image.subscription.reliability:=best_effort' \
  -r image:=/camera1/handeye/debug_image
```

### WSL-7: capture/solve service

각 pose에서 로봇이 완전히 멈춘 뒤 0.5–1초 기다린다. 녹색
`CAPTURE READY`, 가능하면 corners 18 이상, reprojection error 0.5px 이하에서:

```bash
ros2 service call \
  /handeye_calibrator/capture \
  std_srvs/srv/Trigger \
  '{}'
```

sample은 solve 전까지 node RAM에만 있다. hand-eye node를 재시작하거나 reset
서비스를 호출하면 사라진다. 각 응답의 sample 번호/corners/error를 기록한다.
TF skew는 100ms 이하여야 하며 가능하면 50ms 이하를 우선한다. 다음 형식으로
각 결과를 별도 메모에 남긴다.

```text
01 | 화면 중심, 정면 | 24 corners | 0.358 px | 0.0 ms | PASS
-- | 이전 자세와 유사 | REJECT: Pose too similar
```

구현은 직전 저장 pose 대비 translation 15mm 이상 또는 rotation 8deg 이상 중
하나를 만족하면 다음 sample을 허용한다. 이는 전체 pose 다양성을 보장하지
않으므로 같은 위치로 되돌아가는 자세나 한 축만 반복하지 않는다. `success=false`
응답은 sample 수를 증가시키지 않으며 같은 자세에서 capture를 연타하지 않는다.
현재 구현에는 개별 sample 삭제나 outlier 제거가 없으므로 흔들림, 반사, 나쁜
검출을 저장하지 않는 것이 중요하다.

위치와 roll/pitch/yaw가 다양한 20–30 pose를 권장한다. 같은 자세, 한 축 회전만,
순수 translation만 반복하지 않는다. leader를 통해 천천히 변경하고 팔을 끝까지
펴지 않는다.

수집 후:

```bash
ros2 service call \
  /handeye_calibrator/solve \
  std_srvs/srv/Trigger \
  '{}'
```

`quality=PASS`, translation RMS 5mm 이하, rotation RMS 1deg 이하를 요구한다.

```bash
cp "$HOME/.ros/uv_to_world/eye_to_hand.yaml" \
  "$bundle/eye_to_hand.yaml"
```

## 12. 작업대·바닥 평면과 bundle 완성

`environment_planes.yaml`의 패키지 값은 예시다. `link0` 좌표계에서 각 평면을
최소 3x3 grid로 실측하고 `n·x+d=0`의 best-fit 값을 넣는다. 단순히 바닥 높이를
35cm라고 가정하지 않는다.

```bash
cp "$HOME/jazzy_ws/src/uv_to_world/config/runtime/environment_planes.yaml" \
  "$bundle/environment_planes.yaml"
```

복사한 파일을 실측값으로 편집한다. 마지막으로:

```bash
find "$bundle" -maxdepth 2 -type f -print
```

필수 파일:

```text
camera_intrinsics.yaml
eye_to_hand.yaml
environment_planes.yaml
```

이 bundle을 다른 사람에게 전달하면 calibration 코드를 실행하지 않고 runtime만
사용할 수 있다. 자세한 방법은 `docs/03_RUNTIME_ONLY_GUIDE.md`를 따른다.
