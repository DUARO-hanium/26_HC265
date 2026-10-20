# 캘리브레이션 완료 후 좌표변환만 실행하는 가이드

대상 독자는 calibration을 수행하지 않는다. 전달받은 bundle과 현재 workspace만
사용한다. 이 저장소에는 semantic detector가 포함되지 않는다. 따라서 아래 입력
UV 토픽은 별도 detector가 발행해야 한다.

## 전제와 안전

- Ubuntu 24.04/WSL2, ROS 2 Jazzy, 빌드된 `uv_to_world`가 필요하다.
- 카메라 해상도, focus/zoom, 카메라와 로봇 base의 고정 위치가 bundle 생성
  시점과 같아야 한다.
- follower arm은 TF를 얻기 위해 실행할 뿐 자동 이동시키지 않는다.
- 모터 LED 점멸, `Hardware Error`, 비정상 소음/열이 있으면 즉시 motion을
  중단하고 외부 전원을 끈다. 반복 재부팅으로 진행하지 않는다.

## 필요한 파일

```text
<bundle>/
  camera_intrinsics.yaml
  eye_to_hand.yaml
  environment_planes.yaml
```

## 1. 빌드

### WSL-SETUP

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash

cd "$HOME/jazzy_ws"
colcon build --symlink-install --packages-select uv_to_world
source "$HOME/jazzy_ws/install/setup.bash"
```

bundle 경로를 설정하고 검사한다.

```bash
bundle="$HOME/.ros/uv_to_world/calibrations/<profile>"
test -r "$bundle/camera_intrinsics.yaml"
test -r "$bundle/eye_to_hand.yaml"
test -r "$bundle/environment_planes.yaml"
grep -q 'calibration_valid: true' "$bundle/environment_planes.yaml" || {
  echo 'STOP: environment plane bundle is not marked valid'
  return 1
}
```

## 2. Windows 카메라 설정과 실행

### Windows PowerShell — 노출/초점 설정

카메라를 USB에서 다시 꽂은 뒤 장치 이름과 모드를 다시 확인한다. 다음 명령은
Windows PowerShell에서 실행하며 WSL 명령이 아니다.

```powershell
ffmpeg -hide_banner -list_devices true -f dshow -i dummy
ffmpeg -hide_banner -f dshow -show_video_device_dialog true `
  -i 'video=Innomaker-U20CAM-720P  ' -t 1 -f null NUL
```

장치 이름 끝 공백까지 현재 PC에서 열거된 이름과 정확히 일치시킨다. calibration
때 사용한 해상도와 focus/zoom은 바꾸지 않는다. exposure만 조절할 때에도
ChArUco/대상 가장자리가 포화되거나 흔들리지 않는지 확인한다.

### Windows PowerShell — sender

```powershell
$Distro = "<YOUR_WSL_DISTRO>"
$Repo = "\\wsl.localhost\$Distro\home\<USER>\jazzy_ws\src\uv_to_world"
& "$Repo\scripts\windows\start_camera_sender.ps1" `
  -Source mf -DeviceIndex <INDEX> -Width 1280 -Height 720 -Fps 30
```

`gst-device-monitor-1.0.exe Video/Source`로 재연결 후 index를 확인한다. 카메라는
Windows가 소유하므로 `usbipd attach`하지 않는다.

## 3. WSL 카메라 수신과 rectification

receiver에는 전달받은 intrinsics를 명시한다. 각 코드 블록은 별도 WSL 창에서
실행하며, 다른 창의 shell 변수는 공유되지 않는다.

### WSL-CAMERA-RECEIVER

```bash
source /opt/ros/jazzy/setup.bash
bundle="$HOME/.ros/uv_to_world/calibrations/<profile>"

"$HOME/jazzy_ws/src/uv_to_world/scripts/linux/start_gscam_receiver.sh" \
  5000 camera1 "file://$bundle/camera_intrinsics.yaml"
```

이 창에서 `$bundle`이 정의되지 않았다면 먼저 같은 값을 다시 설정한다.

### WSL-RAW-REPUBLISHER

```bash
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

### WSL-RECTIFY

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash
source "$HOME/jazzy_ws/install/setup.bash"

ros2 run image_proc rectify_node --ros-args \
  -r image:=/camera1/image_raw \
  -r camera_info:=/camera1/camera_info \
  -r image_rect:=/camera1/image_rect
```

detector는 `/camera1/image_rect`에서 UV를 구해야 한다. detector가 raw image
UV를 보내면 `uv_is_rectified: true`인 runtime과 좌표 계약이 깨진다.

```bash
timeout 10 ros2 topic hz /camera1/image_rect
ros2 topic echo /camera1/camera_info --once --no-arr
```

## 4. 로봇 TF 실행

좌표변환 runtime은 bundle의 static `link0→camera1_optical_frame`을 직접
발행한다. 따라서 UV→`link0` 계산 smoke test에는 follower hardware가 필수가
아니다. 실제 로봇 모델/관절 TF도 함께 보거나 현장 좌표를 검증할 때만 아래
follower bringup을 시작한다. 자동 teleoperation이나 calibration pose 수집은
실행하지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
source "$HOME/jazzy_ws/install/setup.bash"

ls -l /dev/serial/by-id/
follower_port=$(readlink -f /dev/serial/by-id/<FOLLOWER_BY_ID>)
test -n "$follower_port" || { echo 'STOP: follower not found'; return 1; }

ros2 launch open_manipulator_bringup \
  omx_f_follower_ai.launch.py \
  port_name:="$follower_port" \
  start_rviz:=false \
  init_position:=false
```

## 5. 좌표변환 runtime

### WSL-RUNTIME

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash
source "$HOME/jazzy_ws/install/setup.bash"

bundle="$HOME/.ros/uv_to_world/calibrations/<profile>"

ros2 launch uv_to_world \
  runtime_coordinate_transform.launch.py \
  calibration_dir:="$bundle"
```

이 launch는 다음만 실행한다.

- `eye_to_hand.yaml`에서 `link0→camera1_optical_frame` static TF 발행
- worktop UV→3D projection
- floor UV→3D projection

Checkerboard, ChArUco, hand-eye capture/solve node는 실행하지 않는다.

## 6. 별도 detector 입력과 출력 계약

검출기는 rectified image에서 얻은 pixel을 다음 토픽에
`geometry_msgs/msg/PointStamped`로 보낸다.

```text
/package/entrance_top_uv
/package/bottom_contact_uv
```

- `point.x=u`, `point.y=v`
- `header.stamp`는 원본 이미지 acquisition timestamp
- `header.frame_id=camera1_optical_frame`
- UV는 `/camera1/image_rect` 기준이며 해당 영상의 width/height 안에 있어야 함

출력:

```text
/package/entrance_top_point   # worktop 교점, frame link0
/package/bottom_contact_point # floor 교점, frame link0
```

확인:

```bash
ros2 node info /entrance_top_uv_to_point
ros2 node info /bottom_contact_uv_to_point
timeout 10 ros2 run tf2_ros tf2_echo \
  link0 camera1_optical_frame
```

runtime은 calibration 누락, frame mismatch, timestamp 0, 영상 밖 UV, 해당 시각 TF
누락, 카메라 뒤쪽 교점을 거부한다. 출력이 없을 때 임의 좌표를 대신 사용하지
않는다.

간단한 배선 확인용 입력은 detector 검증을 대신하지 않는다. 실제 영상의 중앙
pixel을 해당 영상 timestamp와 함께 한 번 발행해 출력 토픽이 생기는지만 확인할
수 있다. 운영 정확도 평가는 알려진 3D 기준점으로 별도 수행한다.

## 7. 종료 순서

1. detector를 종료한다.
2. 좌표변환 runtime을 종료한다.
3. follower bringup을 종료하고 torque가 해제됐는지 확인한다.
4. 카메라 receiver/republisher/rectify를 종료한다.
5. Windows sender를 종료한다.

## 8. 재캘리브레이션이 필요한 경우

다음 중 하나라도 바뀌면 기존 bundle을 그대로 사용하지 않는다.

- camera/렌즈 교체
- focus, zoom, 해상도 변경
- 카메라 고정 위치나 방향 변경
- robot base 위치 변경
- worktop/floor 위치 변경
- frame 이름 또는 URDF 변경

노출만 바꾸고 focus/zoom/해상도와 장착이 그대로라면 보통 intrinsics는 유지할
수 있지만, 검출 품질 검증은 다시 한다.
