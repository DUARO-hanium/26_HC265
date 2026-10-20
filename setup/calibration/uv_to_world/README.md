# uv_to_world

ROS 2 Jazzy와 고정 RGB 카메라로 비닐 패키지의 두 접촉점을 로봇 기준 3D
좌표로 변환한다.

이 저장소가 제공하는 핵심은 calibration과 **외부 detector가 발행한 rectified
pixel UV를 `link0`의 3D 점으로 변환하는 runtime**이다. 패키지 landmark를
영상에서 찾는 semantic detector 자체는 포함하지 않는다. 실제 측정 calibration
bundle도 저장소에 포함하지 않는다.

## Clone 후 최초 빌드

Ubuntu 24.04와 ROS 2 Jazzy가 설치된 WSL에서 실행한다.

```bash
mkdir -p "$HOME/jazzy_ws/src"
cd "$HOME/jazzy_ws/src"
git clone \
  https://github.com/DUARO-hanium/omx-ai-uv-to-world.git \
  uv_to_world

source /opt/ros/jazzy/setup.bash
cd "$HOME/jazzy_ws"
rosdep update
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select uv_to_world
source "$HOME/jazzy_ws/install/setup.bash"
colcon test --packages-select uv_to_world
colcon test-result --verbose
```

GStreamer system plugin은 별도로 설치한다.

```bash
sudo apt-get install -y \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad
```

실제 robot TF가 필요한 calibration 단계에는 별도
[ROBOTIS OpenManipulator](https://github.com/ROBOTIS-GIT/open_manipulator)
workspace가 필요하다. 이미 측정된 `link0→camera` bundle의 순수 UV→3D
runtime은 로봇을 움직이지 않고도 시험할 수 있다.

## 운영 문서

- 처음부터 USB 재연결·내부보정·hand-eye까지:
  [`docs/01_FULL_CALIBRATION_GUIDE.md`](docs/01_FULL_CALIBRATION_GUIDE.md)
- 캘리브레이션 결과물 규격과 인계:
  [`docs/02_CALIBRATION_ARTIFACT_HANDOFF.md`](docs/02_CALIBRATION_ARTIFACT_HANDOFF.md)
- 결과 bundle만 받아 좌표변환 실행:
  [`docs/03_RUNTIME_ONLY_GUIDE.md`](docs/03_RUNTIME_ONLY_GUIDE.md)
- 별도 Zenoh/Cyclo 데이터 수집 운영:
  [`omx-f-zenoh-data-collection`](https://github.com/DUARO-hanium/omx-f-zenoh-data-collection)

상세 절차는 위 문서를 기준으로 한다. 이 README의 나머지 내용은 설계 개요다.

- 입구 최상부 접촉점은 작업대 상판 평면 위에 있다.
- 패키지 하단 접촉점은 항상 바닥 평면 위에 있다.

비닐은 변형되므로 패키지에 붙인 ArUco pose를 패키지 전체의 rigid pose로
사용하지 않는다. Checkerboard는 내부보정, tool 장착 ChArUco는 고정 카메라와
로봇 base 사이 외부보정에만 사용한다.

## 최종 데이터 흐름

```text
Windows Innomaker RGB camera
  → MJPEG/RTP/UDP
  → WSL ROS Image + calibrated CameraInfo
  → image_proc rectification
  → semantic detector
       ├─ /package/entrance_top_uv
       └─ /package/bottom_contact_uv
  → two named ray-plane projections
       ├─ worktop → /package/entrance_top_point
       └─ floor   → /package/bottom_contact_point
```

두 입력은 `geometry_msgs/msg/PointStamped`이며 `(point.x, point.y)`가 rectified
pixel `(u,v)`다. `header.stamp`는 원본 이미지 acquisition timestamp,
`header.frame_id`는 `camera1_optical_frame`이어야 한다.

## 저장소 구조

```text
config/
  calibration/                  # ChArUco calibration 기본 파라미터
  runtime/                      # fail-closed runtime 예제
launch/
  handeye_calibration.launch.py
  runtime_coordinate_transform.launch.py
scripts/windows/
  start_camera_sender.ps1
uv_to_world/
  calibration/                  # calibration-only 구현
  runtime/                      # bundle consumer와 UV→3D 구현
test/
docs/
artifacts/
```

## 1. ROS 도구 설치

Conda 대신 시스템 ROS Python을 사용한다.

```bash
conda deactivate 2>/dev/null || true
source /opt/ros/jazzy/setup.bash
sudo apt-get update
sudo apt-get install -y \
  ros-jazzy-camera-calibration \
  ros-jazzy-image-view \
  ros-jazzy-tf2-tools
```

## 2. 빌드와 테스트

```bash
cd ~/jazzy_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select uv_to_world
source install/setup.bash
colcon test --packages-select uv_to_world
colcon test-result --verbose
```

## 3. Windows 카메라 전송

카메라는 Windows 소유 `Shared` 상태로 두고 `usbipd attach`하지 않는다.
현재 Innomaker 카메라는 Media Foundation의 zero-based device index `1`에서
MJPEG 1280×720 30 Hz와 RTP/JPEG payloader를 검증했다. index는 Windows 장치
열거 순서가 바뀌면 달라질 수 있으므로 재연결 후에는 device monitor로 확인한다.

```powershell
$gstDir = "$env:LOCALAPPDATA\Programs\gstreamer\1.0\msvc_x86_64\bin"
& "$gstDir\gst-device-monitor-1.0.exe" Video/Source
```

```powershell
$Distro = "<YOUR_WSL_DISTRO>"
$User = "<YOUR_WSL_USER>"
$script = "\\wsl.localhost\$Distro\home\$User\jazzy_ws\src\uv_to_world\scripts\windows\start_camera_sender.ps1"
& $script -Source mf -DeviceIndex 1 -Width 1280 -Height 720 -Fps 30
```

이 카메라의 MF JPEG stream은 `jpegparse`와 호환되지 않았지만
`rtpjpegpay`에는 직접 연결되어 300 frame 연속 시험을 통과했다. 따라서 MF
branch에는 `jpegparse`를 넣지 않는다. KS fallback은 아직 end-to-end 검증되지
않았으며, 별도 KS path를 명시할 때만 기존 `jpegparse` 경로로 시험한다.

1280×720에서 29–31 Hz와 허용 지연이 나오지 않으면 640×480을 별도로
시험한다. 최종 모드를 고른 뒤에만 내부보정을 수행한다.

## 4. 카메라 토픽 계약

WSL host에는 Docker나 gscam이 기본 설치되어 있지 않을 수 있다. 이 저장소의
receiver는 host ROS 2에서 직접 실행한다.

```bash
sudo apt-get install -y \
  ros-jazzy-gscam \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad
~/jazzy_ws/src/uv_to_world/scripts/linux/start_gscam_receiver.sh 5000 camera1
```

별도 터미널에서 압축 영상을 표준 raw Image로 변환한다.

```bash
source /opt/ros/jazzy/setup.bash
ros2 run image_transport republish --ros-args \
  -p in_transport:=compressed \
  -p out_transport:=raw \
  -p 'qos_overrides./camera1/image_raw/compressed.subscription.reliability:=best_effort' \
  -r in/compressed:=/camera1/image_raw/compressed \
  -r out:=/camera1/image_raw
```

republisher는 raw 출력에 subscriber가 붙을 때 compressed 입력 subscription을
생성한다. 입력 subscription은 gscam의 sensor-data publisher와 동일하게
`BEST_EFFORT`를 사용해야 하며, raw output publisher는 기본 `RELIABLE`이다.
`ros2 topic info /camera1/image_raw/compressed --verbose`에서 두 compressed
endpoint가 모두 `BEST_EFFORT`인지 확인한다.

receiver는 최소 다음을 발행해야 한다.

```text
/camera1/image_raw
/camera1/camera_info
```

확인:

```bash
ros2 topic hz /camera1/image_raw
ros2 topic echo /camera1/camera_info --once
```

`CameraInfo`의 width/height는 이미지와 같고, K의 `fx/fy`는 0이 아니며,
`frame_id`는 `camera1_optical_frame`이어야 한다.

## 5. Checkerboard 내부보정

최종 해상도에서 실제 square 길이를 미터로 넣는다. 현재 출력한 checkerboard의
검정 square 한 변은 `24 mm`이므로 `0.024 m`를 사용한다. `--size`는 사각형
수가 아니라 내부 corner 수다.

```bash
ros2 run camera_calibration cameracalibrator \
  --size 8x6 \
  --square 0.024 \
  image:=/camera1/image_raw \
  camera:=/camera1 \
  --no-service-check
```

화면 중앙·네 모서리·near/far·여러 기울기에서 수집한다. 저장된 calibration
YAML은 receiver의 `camera_info_url`에 연결한다.

## 6. Rectified image

로컬 Jazzy launch 인자를 먼저 확인한다.

```bash
ros2 launch image_proc image_proc.launch.py --show-args
ros2 launch image_proc image_proc.launch.py namespace:=camera1
ros2 topic list | grep image_rect
```

검출기는 실제로 생성된 rectified topic만 사용한다. calibration YAML을
로드하는 것만으로 영상이 rectified되는 것은 아니다.

## 7. camera↔robot base 외부보정

ChArUco 보드를 `end_effector_link`에 강체 고정한다. 실행 중인 TF에서 실제
OMX-F의 실제 base frame인 `link0`이 TF에 존재하는지 먼저 확인하고
`config/handeye_calibration.yaml`을 맞춘다.

현재 ChArUco는 명목 크기의 96%로 출력되었으므로 우선
`square_length: 0.024`, `marker_length: 0.01728`을 사용한다. 보정 전에 서로
떨어진 여러 square와 검은 marker 외곽을 가로·세로로 직접 재어 균일 축소인지
확인한다. 직접 측정한 평균값이 다르면 그 값을 미터로 config에 입력한다.

```bash
ros2 run tf2_tools view_frames
ros2 launch uv_to_world handeye_calibration.launch.py
```

검출 오버레이는 `/camera1/handeye/debug_image`로 발행된다. 녹색
`CAPTURE READY` 상태에서 검출 corner 수와 reprojection error를 확인한다.
카메라가 robot TF보다 빠르므로 별도 executor thread에서 최대 200 ms 기다려
영상의 정확한 timestamp에 해당하는 TF를 사용한다. 로봇이 완전히 정지한
뒤에만 capture한다.

로봇을 매번 완전히 정지시키고 서로 다른 위치와 roll/pitch/yaw에서 20–30개
sample을 모은다.

```bash
ros2 service call /handeye_calibrator/capture std_srvs/srv/Trigger
ros2 service call /handeye_calibrator/solve std_srvs/srv/Trigger
ros2 launch uv_to_world calibrated_camera_tf.launch.py
ros2 run tf2_ros tf2_echo <actual_base_frame> camera1_optical_frame
```

## 8. 작업대와 바닥 평면 계측

`35 cm`를 그대로 config에 넣지 않는다. 동일한 robot target frame에서 상판과
바닥을 각각 최소 3×3 grid로 측정하고 best-fit plane을 구한다.

```text
n.x*x + n.y*y + n.z*z + d = 0
```

수평이고 base 원점이 정확히 상판이라면 예시는 다음과 같다.

```yaml
worktop: normal=[0,0,1], offset=0.0
floor:   normal=[0,0,1], offset=0.35   # z=-0.35
```

이는 예시일 뿐이다. 실측한 `normal`, `offset`, 실제 base frame을
`config/environment_planes.yaml`에 넣는다.

## 9. 두 평면 projection 실행

```bash
bundle="$HOME/.ros/uv_to_world/calibrations/<profile>"
ros2 launch uv_to_world runtime_coordinate_transform.launch.py \
  calibration_dir:="$bundle"
ros2 node info /entrance_top_uv_to_point
ros2 node info /bottom_contact_uv_to_point
```

의미는 launch에서 고정된다.

```text
/package/entrance_top_uv
  → worktop plane
  → /package/entrance_top_point

/package/bottom_contact_uv
  → floor plane
  → /package/bottom_contact_point
```

노드는 다음 입력을 거부하고 아무 좌표도 발행하지 않는다.

- calibration 없음 또는 focal length 0
- NaN/Inf 또는 영상 범위 밖 UV
- UV frame과 CameraInfo optical frame 불일치
- acquisition timestamp가 0
- 해당 timestamp의 TF 없음
- 평면과 거의 평행한 ray
- 카메라 뒤쪽 교점

## 10. 검증

상판과 바닥에 각각 3×3 이상 실제 좌표가 알려진 점을 표시한다. 화면 중앙과
가장자리를 포함해 점마다 30회 측정한다.

- XY bias, 표준편차, p95, 최대오차
- 잘못된 좌표를 유효하게 발행한 false-valid 비율
- 영상 FPS와 capture→point p95/p99 latency
- 입구와 하단 접촉이 풀렸을 때 좌표를 소비하지 않는 공정 interlock

비닐 중간 표면, 공중에 뜬 점, 입구/하단의 접촉이 깨진 상태는 이 모델의 출력
범위가 아니다.

## 공식 기준

- ROS image pipeline: <https://docs.ros.org/en/jazzy/p/image_pipeline/>
- ROS monocular calibration:
  <https://docs.ros.org/en/kilted/p/camera_calibration/doc/tutorial_mono.html>
- ROS image_geometry: <https://docs.ros.org/en/jazzy/p/image_geometry/>
- ROS tf2: <https://docs.ros.org/en/jazzy/p/tf2/generated/doxygen/html/index.html>
- GStreamer mfvideosrc:
  <https://gstreamer.freedesktop.org/documentation/mediafoundation/mfvideosrc.html>
- GStreamer rtpjpegpay:
  <https://gstreamer.freedesktop.org/documentation/rtp/rtpjpegpay.html>
- GStreamer queue:
  <https://gstreamer.freedesktop.org/documentation/coreelements/queue.html>
- GStreamer udpsink:
  <https://gstreamer.freedesktop.org/documentation/udp/udpsink.html>
