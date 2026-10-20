# 캘리브레이션 결과물 생성·인계 가이드

이 문서는 캘리브레이션 담당자가 runtime 사용자에게 무엇을 전달해야 하는지
정의한다. 실제 결과 파일은 Git에 기본값으로 commit하지 않는다.

## 디렉터리 계약

```text
~/.ros/uv_to_world/calibrations/<profile>/
  camera_intrinsics.yaml
  eye_to_hand.yaml
  environment_planes.yaml
  manifest.yaml
  reports/
    intrinsic_ost.txt
    tf_frames.pdf
    validation.md
```

필수 파일은 앞의 세 YAML이다.

## `camera_intrinsics.yaml`

ROS `camera_calibration`의 SAVE 결과인 `ost.yaml`을 이름만 바꾼다. 최소 확인:

- `image_width: 1280`
- `image_height: 720`
- `camera_name: camera1`
- `distortion_model: plumb_bob`
- camera matrix의 fx/fy가 0이 아님
- 실제 사용한 focus/zoom/exposure와 1280x720 mode가 이후에도 동일함

수치를 문서에서 손으로 다시 타이핑하지 말고 원본 YAML을 전달한다.

## `eye_to_hand.yaml`

runtime이 요구하는 핵심 구조:

```yaml
calibration:
  parent_frame: link0
  child_frame: camera1_optical_frame
  translation: [x, y, z]
  quaternion_xyzw: [x, y, z, w]
  sample_count: 20
  translation_rms_m: 0.003
  rotation_rms_deg: 0.5
  solver_smallest_singular_value: 0.1
  quality_passed: true
```

runtime은 `quality_passed: true`가 아니면 TF 발행을 거부한다. translation 단위는
meter, quaternion 순서는 `xyzw`다.

## `environment_planes.yaml`

ROS parameter file이며 node 이름을 변경하지 않는다.

```yaml
entrance_top_uv_to_point:
  ros__parameters:
    target_frame: link0
    plane_normal: [nx, ny, nz]
    plane_offset: d

bottom_contact_uv_to_point:
  ros__parameters:
    target_frame: link0
    plane_normal: [nx, ny, nz]
    plane_offset: d
```

평면식은 `nx*x + ny*y + nz*z + d = 0`이다. normal과 offset 모두 같은
`link0` 좌표계의 실측값이어야 한다.

## 인계 전 검증

```bash
bundle="$HOME/.ros/uv_to_world/calibrations/<profile>"

test -r "$bundle/camera_intrinsics.yaml"
test -r "$bundle/eye_to_hand.yaml"
test -r "$bundle/environment_planes.yaml"

grep -n 'quality_passed: true' "$bundle/eye_to_hand.yaml"
grep -nE 'image_width: 1280|image_height: 720' \
  "$bundle/camera_intrinsics.yaml"
```

실행 검증:

```bash
source /opt/ros/jazzy/setup.bash
source "$HOME/jazzy_ws/install/setup.bash"

ros2 launch uv_to_world \
  runtime_coordinate_transform.launch.py \
  calibration_dir:="$bundle"
```

별도 창:

```bash
timeout 10 ros2 run tf2_ros tf2_echo \
  link0 camera1_optical_frame
```

알려진 상판점과 바닥점 각각 최소 3x3 위치에서 XY 오차를 기록하고
`reports/validation.md`에 bias, 표준편차, p95, 최대오차를 남긴다.

## Git 정책

Git에는 코드, schema/example, 문서만 올린다. 실제 현장 calibration은
`~/.ros/uv_to_world/calibrations/`에 보관하고 필요한 profile만 별도 전달한다.
카메라 교체, 렌즈/focus/zoom/해상도 변경, 카메라 또는 robot base 이동,
ChArUco 장착 변경 후에는 관련 calibration을 다시 수행한다.
