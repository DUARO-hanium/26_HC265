# 봉지 안쪽 진입 Motion Planning

## 연동 구조

uv_to_world 패키지 (별도 레포)

→ `/package/entrance_top_point` 토픽 발행 (geometry_msgs/PointStamped)

bag_insertion.py

→ `/package/entrance_top_point` 토픽 구독
→ entry(입구) → waypoint(방향 전환) → target(옷 위치) 순서로
  waypoint를 하나씩 순차 plan+execute
→ MoveIt2로 실행

두 레포는 코드를 직접 공유하지 않고 ROS2 토픽 통신으로만 연결됨.

---

## Planner 선택

waypoint를 하나씩 `set_goal_state()` + `plan()` + `execute()`로 순차 실행하는 방식 채택 (원래 계획했던 Cartesian Path는 MoveItPy 버전 제약으로 미지원, 상세 내용은 [troubleshooting/moveit_py.md](../../setup/docs/troubleshooting/moveit_py.md) 참고).
더 매끄러운 경로가 필요하면 ROS2 액션 직접 호출이나 ikpy 기반 trajectory 조립 등 대안 검토 가능.

Planning Scene(충돌 회피)은 봉지 벽 형상 미확정으로 이번 단계에서 제외. waypoint 자체를 안전하게 잡는 것으로 대신하며, 벽 크기 확정되면 collision object로 보강 예정.

---

## 사전 준비

- uv_to_world 패키지가 빌드되어 `/package/entrance_top_point` 토픽을 발행 중이어야 함 (없어도 placeholder 좌표로 독립 실행 가능)
- moveit_py import 확인 필요 → [troubleshooting/moveit_py.md](../../setup/docs/troubleshooting/moveit_py.md) 참고
- dynamixel_hardware_interface 설치 확인 (실물 로봇 사용 시) → [troubleshooting/omx_l_setup.md](../../setup/docs/omx_l_setup.md) 참고
- 로봇 USB 연결 및 usbipd attach

---

## 스크립트

[`src/bag_insertion.py`](../src/bag_insertion.py)
[`src/moveit_cpp_config.yaml`](../src/moveit_cpp_config.yaml)

---

## 포트 확인 (매번 필수)

USB 꽂는 순서에 따라 `/dev/ttyACM0`, `/dev/ttyACM1` 등 번호가 매번 바뀔 수 있음. 아래 명령어로 반드시 먼저 확인 후 진행.

```bash
conda activate lerobot
lerobot-find-port
```

또는

```bash
ls /dev/ttyACM*
```

두 로봇이 동시에 연결된 상태라면, `lerobot-find-port`로 하나씩 케이블 뽑아가며 포트 번호 확인 (02_lerobot_teleoperation.md 참고).

---

## 로봇별 실행 값

⚠️ 아직 Leader/Follower 중 어느 팔이 이 동작(봉지 안쪽 진입)을 맡을지 확정되지 않아, 두 경우 모두 바로 시도해볼 수 있도록 정리해둠.

| 항목 | Leader (omx_l) | Follower (omx_f) |
|---|---|---|
| bringup launch | `open_manipulator_bringup omx_l_leader_ai.launch.py` | `open_manipulator_bringup omx_f.launch.py` |
| moveit launch | `omx_l demo.launch.py` | `open_manipulator_moveit_config omx_f_moveit.launch.py` |
| MoveItConfigsBuilder robot_name | `"omx_l"` | `"omx_f"` |
| MoveItConfigsBuilder package_name | `"omx_l"` | `"open_manipulator_moveit_config"` |

---

## 실행

### 터미널 1 — Zenoh 데몬 (계속 켜두기, 공통)
```bash
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
ros2 run rmw_zenoh_cpp rmw_zenohd
```

### 터미널 2 — 로봇 실물 하드웨어

위 "포트 확인" 단계에서 확인한 실제 포트 번호를 입력할 것.

**Leader:**
```bash
sudo chmod 666 <포트번호>

source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
ros2 launch open_manipulator_bringup omx_l_leader_ai.launch.py port_name:=<포트번호>
```

**Follower:**
```bash
sudo chmod 666 <포트번호>

source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
ros2 launch open_manipulator_bringup omx_f.launch.py port_name:=<포트번호>
```
> mock으로 먼저 테스트하려면 `port_name` 대신 `use_mock_hardware:=true`

### 터미널 2-2 — MoveIt2 + RViz

**Leader:**
```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
ros2 launch omx_l demo.launch.py
```

**Follower:**
```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
ros2 launch open_manipulator_moveit_config omx_f_moveit.launch.py
```

### 터미널 3 — uv_to_world runtime (선택, 실제 좌표 연동 시)
```bash
source /opt/ros/jazzy/setup.bash
bundle="$HOME/.ros/uv_to_world/calibrations/<profile>"
ros2 launch uv_to_world runtime_coordinate_transform.launch.py \
  calibration_dir:="$bundle"
```

토픽 발행 확인:
```bash
ros2 topic echo /package/entrance_top_point
```

### 터미널 4 — bag_insertion.py 실행

스크립트 안의 `MoveItConfigsBuilder("omx_l", package_name="omx_l")` 부분을 Follower로 실행할 땐 `MoveItConfigsBuilder("omx_f", package_name="open_manipulator_moveit_config")`로 바꿔야 함.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
python3 ~/bag_insertion.py
```

---

## 안전 체크리스트

- [ ] 로봇 주변에 부딪힐 물건 없는지 확인
- [ ] entry_xyz, waypoint_xyz, target_xyz 값이 실측/검증된 값인지 확인 (placeholder 값 그대로면 위험할 수 있음)
- [ ] 언제든 Ctrl+C로 중단 가능하도록 대기

---

## 앞으로 확인/진행해야 할 것

- [ ] home 자세 재측정: link0-link5 충돌 발생, Leader 실물로 안전한 값 실측 필요
- [ ] SYNC_READ_FAIL 원인 확정: WSL2 usbipd 지연으로 추정, 네이티브 Ubuntu에서 재검증 필요
- [ ] joint_trajectory_command_broadcaster 빌드 에러 확인: 로그 확보 후 원인 파악 필요
- [ ] target_xyz(옷 위치) vision 연동: uv_to_world 범위 밖, FashionAI 등 별도 좌표 소스 연결 필요
- [ ] waypoint_xyz 실측: 현재 placeholder, 텔레오퍼레이션으로 방향 전환 지점 측정 필요

---

## 참고
- uv_to_world 레포: https://github.com/DUARO-hanium/omx-ai-uv-to-world
