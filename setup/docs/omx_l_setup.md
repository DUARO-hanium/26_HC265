# Leader(omx_l) MoveIt2 세팅

기존 open_manipulator_moveit_config 패키지에는 omx_f, omy_3m, omy_f3m, open_manipulator_x용 설정만 있고 omx_l(Leader)용 SRDF/config가 없어서 직접 생성함.

## 생성 방법

MoveIt Setup Assistant 사용

```bash
ros2 launch moveit_setup_assistant setup_assistant.launch.py
```

### 1. URDF 로드

xacro 직접 로드 시 "not a valid robot model" 에러 발생. 순수 .urdf로 변환 후 로드해야 함.

```bash
xacro ~/ros2_ws/src/open_manipulator/open_manipulator_description/urdf/omx_l/omx_l.urdf.xacro > /tmp/omx_l_test.urdf
```

Setup Assistant의 Browse 창에서 `/tmp/omx_l_test.urdf` 선택 후 Load Files.

### 2. Self-Collisions

Self-Collisions 탭 → Generate Collision Matrix 클릭.

결과: link0-link1, link1-link2, link2-link3, link3-link4, link4-link5, link5-link6 (Adjacent Links)

### 3. Planning Groups

- **arm**: Kinematic Chain, Base Link: link0, Tip Link: link5 (joint1~5 자동 포함)
- **gripper**: Add Joints 방식으로 gripper_joint_1 추가

### 4. Robot Poses

- **init**: 전체 관절 0도
- **home**: omx_f 값(joint2=-1.57, joint3=1.57, joint4=1.57) 그대로 사용
  - ⚠️ 이 값으로 link0-link5 충돌 발생 확인됨. 실측 후 재설정 필요.

### 5. End Effectors

- Name: leader_gripper
- Parent Link: link5
- Group: gripper
- Parent Group: arm

### 6. Configuration Files

저장 경로 지정 시 `open_manipulator_moveit_config/config/omx_l`로 지정하면 **독립된 새 ROS2 패키지**로 생성됨 (omx_f처럼 기존 패키지 하위 폴더가 아님).

생성 후 위치를 옮김:

```bash
mv ~/ros2_ws/src/open_manipulator/open_manipulator_moveit_config/config/omx_l \
   ~/ros2_ws/src/open_manipulator/omx_l_moveit_config
```

---

## 생성 후 수동 수정 필요했던 것

### 1. package.xml — maintainer 이메일 누락

```
Invalid email "" for person ""
Maintainers must have an email address
```

`<maintainer email="">` 가 비어있어서 colcon build 실패. 이메일 채워넣어야 함.

```xml
<maintainer email="your_email@example.com">your_name</maintainer>
```

패키지 이름(`<name>`)도 확인 필요 — colcon build 시 폴더명이 아니라 이 `<name>` 값으로 패키지를 찾음.

### 2. .setup_assistant — URDF package 경로 비어있음

URDF를 `/tmp` 경로로 로드했기 때문에 어느 패키지에도 속하지 않는다고 기록됨:

```yaml
urdf:
  package: ""
  relative_path: /tmp/omx_l_test.urdf
```

이 상태로 launch하면 아래 에러 발생:

```
ValueError: '' is not a valid package name
```

수동으로 수정:

```yaml
moveit_setup_assistant_config:
  urdf:
    package: "open_manipulator_description"
    relative_path: urdf/omx_l/omx_l.urdf.xacro
  srdf:
    relative_path: config/omx_l.srdf
  package_settings:
    author_name: "your_name"
    author_email: "your_email@example.com"
```

### 3. ompl_planning.yaml 누락

Setup Assistant가 이 파일을 생성해주지 않음. 다른 로봇들과 공유하는 공통 위치에 이미 존재하는 파일을 복사해서 사용.

```bash
cp ~/ros2_ws/src/open_manipulator/open_manipulator_moveit_config/config/ompl_planning.yaml \
   ~/ros2_ws/src/open_manipulator/omx_l_moveit_config/config/
```

내용 (로봇마다 공통, group 이름 의존성 없음):

```yaml
planning_plugins:
  - ompl_interface/OMPLPlanner
request_adapters:
  - default_planning_request_adapters/ResolveConstraintFrames
  - default_planning_request_adapters/ValidateWorkspaceBounds
  - default_planning_request_adapters/CheckStartStateBounds
  - default_planning_request_adapters/CheckStartStateCollision
response_adapters:
  - default_planning_response_adapters/AddTimeOptimalParameterization
  - default_planning_response_adapters/ValidateSolution
  - default_planning_response_adapters/DisplayMotionPath
```

### 4. joint_limits.yaml — acceleration 값 누락

Setup Assistant가 자동 생성한 값 전부 `has_acceleration_limits: false`, `max_acceleration: 0`으로 되어있음. URDF 자체에 acceleration 정보가 없어서 Setup Assistant가 채우지 못함.

이 상태로 Plan 시도하면:

```
[ERROR]: No acceleration limit was defined for joint joint1!
```

수동으로 omx_f 값을 참고해 수정:

```yaml
default_velocity_scaling_factor: 0.1
default_acceleration_scaling_factor: 0.1
joint_limits:
  joint1:
    has_velocity_limits: true
    max_velocity: 5.0
    has_acceleration_limits: true
    max_acceleration: 5.0
```

joint2~5, gripper_joint_1도 동일하게 수정.

---

## 검증 결과

RViz + MoveIt2(`ros2 launch omx_l demo.launch.py`)에서 Goal State "init" 자세로 Plan 성공 확인.

"home" 자세는 link0-link5 충돌로 Plan 실패 (`Unable to sample any valid states for goal tree`). omx_f 값을 그대로 가져와서 Leader 팔 구조에 안 맞는 값이었던 것으로 추정. 실측 후 재설정 필요.

---

## 실물 로봇 연결 시 참고

### dynamixel_hardware_interface 미설치

```
[ERROR]: According to the loaded plugin descriptions the class
dynamixel_hardware_interface/DynamixelHardware ... does not exist.
Declared types are mock_components/GenericSystem
```

설치 필요:

```bash
sudo apt install ros-jazzy-dynamixel-hardware-interface
```

설치 후 open_manipulator_bringup, open_manipulator_description 재빌드 필요.

### joint_trajectory_command_broadcaster 로드 실패

```
[ERROR]: Loader for controller 'joint_trajectory_command_broadcaster'
(type 'joint_trajectory_command_broadcaster/JointTrajectoryCommandBroadcaster') not found.
```

커스텀 패키지(om_joint_trajectory_command_broadcaster)가 빌드 실패 상태로 확인됨. 미해결. 다른 컨트롤러(joint_state_broadcaster, trigger_position_controller)는 정상 동작하므로 텔레오퍼레이션 자체엔 지장 없음.

### SYNC_READ_FAIL 반복 (WSL2 환경)

실물 로봇 연결 시 기본 update_rate(100Hz) 기준으로 통신 read/write가 지속적으로 timeout 발생:

```
FastSyncRead Rx Fail [Dxl Size : 6] [Error code : -3002]
Dynamixel Read Fail (Duration: 10.xxms/500ms)
```

USB 허브 제거 후 PC 직결 시도해도 유의미한 개선 없음.

hardware_controller_manager.yaml의 update_rate를 100 → 30으로 낮추면 실패 빈도는 감소하지만 완전 해결은 안 됨 (여전히 주기 경계선에서 아슬아슬하게 timeout 발생):

```yaml
controller_manager:
  ros__parameters:
    update_rate: 30  # Hz
```

WSL2 usbipd 패스스루의 근본적인 지연 특성으로 추정. 네이티브 Ubuntu 환경에서 재검증 필요 (미해결).

## 참고

- open_manipulator: https://github.com/ROBOTIS-GIT/open_manipulator
- 04_camera_moveit.md (goal 좌표 측정 방법)
