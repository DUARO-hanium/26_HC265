# omx-robot-motion

OMX-F 팔에 **베이스(link0) 기준 3D 좌표 (x, y, z)[m]** 를 주면 그 위로 이동해 수직으로 내려가고, 옵션으로 **그리퍼를 닫아 잡고 들어 올리는** 스크립트. MoveIt 없이 관절각을 직접 계산해 `JointTrajectory` 로 보낸다.

```
(x, y, z) --> 사전위치(목표 위 6 cm) --> 수직 하강 --> [그리퍼 닫기 --> 파지 판정 --> 들기 --> 놓기]
```

## 파일

| 파일 | 역할 |
|---|---|
| `go_down.py` | 실행 파일. 좌표 입력, 하강, 그리퍼, 들기 |
| `omx_ik.py` | FK/IK 계산기 (ROS 불필요). `go_down.py` 가 불러 씀 |
| `coord_conversion/` | 화면 픽셀 -> 로봇 좌표 변환이 없을 때 쓰는 대체 경로 (`homography_map.py`, `watch_and_go.py`, `json_to_xyz.py`) |
| `omx_f_dual.launch.py` | 두 팔 네임스페이스 런치 초안 (실기 미검증) |
| `docs/hardware_checklist.md` | 실기 점검 순서와 실측 기록 |

## 설치

```bash
pip install numpy                      # omx_ik.py, go_down.py
pip install opencv-python pyyaml       # coord_conversion 을 쓸 때만
```
ROS 패키지가 아니라 Python 파일 묶음이므로 `colcon build` 없이 폴더 안에서 바로 실행한다. 로봇을 움직일 때는 ROS 2 Jazzy 를 `source` 한 터미널에서 실행한다 (venv 안에서는 `rclpy` 가 안 보일 수 있음).

## 런치 선택

그리퍼 전송 방식이 런치마다 다르다. `--grip-mode auto` 가 아래 순서로 자동 판별한다.

| 런치 | 팔 궤적 토픽 | 그리퍼 | `go_down.py` 옵션 |
|---|---|---|---|
| `omx_f.launch.py` | `/arm_controller/joint_trajectory` | `gripper_controller` 액션 `/gripper_controller/gripper_cmd` | 기본값 그대로 |
| `omx_f_follower_ai.launch.py` | `/leader/joint_trajectory` (리맵됨) | `arm_controller` 의 6번째 관절 `gripper_joint_1` | `--traj-topic /leader/joint_trajectory` (그리퍼는 자동으로 traj 방식) |

```bash
ros2 launch open_manipulator_bringup omx_f.launch.py port_name:=/dev/ttyACM0
ros2 control list_controllers          # arm_controller, gripper_controller, joint_state_broadcaster 가 active 인지
ros2 control list_hardware_interfaces  # gripper_joint_1/position 이 [available] [claimed] 인지
```
`gripper_joint_1` 이 `[unavailable]` 이면 그리퍼 모터(ID 16)가 에러 상태로 켜졌거나 하드웨어 인터페이스 초기화가 실패한 것이다. 아래 "런치 전 점검" 을 먼저 하고, 런치 로그에서 ID 16 관련 에러를 본다.

## 런치 전 점검 (매번)

1. **전원 순서**: 12 V -> 5 V -> USB (OMX-Setup-Guide 권장 순서). 2026-10-19 점검에서 XL430(ID 11~13) 세 개에 Input Voltage 에러가 잠겨 있던 적이 있다. 전원 투입 중 전압 변동이 원인으로 추정되며, 잠기면 리부트 전까지 토크가 안 걸린다.
2. **모터 에러 확인**: Dynamixel Wizard 로 ID 11~16 의 Hardware Error Status(주소 70)가 모두 0 인지 본다. 0 이 아니면 해당 모터를 Reboot 한다. 런치 중이면 서비스로도 된다.
   ```bash
   ros2 service call /dynamixel_hardware_interface/reboot_dxl dynamixel_interfaces/srv/RebootDxl "{}"
   ```
3. **팔 자세**: 토크가 풀린 채 처진 자세에서는 관절 2(ID 12)가 xacro 의 Min Position Limit(830 틱) 아래로 내려가 있을 수 있다(2026-10-19 측정 745). 런치 전에 팔을 살짝 들어 접힌 자세로 둔다.
4. **그리퍼 초기 목표(`omx_f_follower_ai.launch.py` 만 해당)**: `open_manipulator_bringup/config/omx_f_follower_ai/initial_positions.yaml` 의 `gripper_joint_1` 이 `0.0` 이면 열림 끝 바깥(2048 틱)으로 밀어 모터가 손상된다. 아래 실측한 열림 값 근처로 바꾼 뒤 런치한다.

## 그리퍼 값 실측 (모터를 바꾸거나 Homing Offset 이 바뀌면 다시)

`--grip-open`, `--grip-close` 는 기본값이 없다. 실제 관절값으로 잰다.

```bash
# 1) 런치 상태에서 토크를 푼다
ros2 service call /dynamixel_hardware_interface/set_dxl_torque std_srvs/srv/SetBool "{data: false}"
# 2) 손으로 그리퍼를 열림 끝, 닫힘 끝까지 움직이며 값을 읽는다
ros2 topic echo /joint_states --field name --once
ros2 topic echo /joint_states --field position        # gripper_joint_1 자리의 값을 기록
# 3) 토크를 다시 건다
ros2 service call /dynamixel_hardware_interface/set_dxl_torque std_srvs/srv/SetBool "{data: true}"
```
- 열림 값 = 열림 끝에서 **닫힘 쪽으로 0.1 rad 이상** 안쪽. 닫힘 값 = 닫힘 끝에서 **열림 쪽으로 0.1 rad 이상** 안쪽. 양 끝을 그대로 쓰면 하드스톱을 밀게 된다.
- `go_down.py` 는 두 값 사이로만 명령한다(클램프). 더 좁히려면 `--grip-limit LO HI`.
- 2026-10-11 실측(모터 교체 전, Homing Offset 23): 열림 끝 1775 틱, 닫힘 끝 639 틱. 틱과 rad 대응은 `rad = (틱 - 2048) * 2π / 4096` 이지만 Homing Offset 에 따라 달라지므로 위처럼 `/joint_states` 로 직접 읽는 값을 쓴다.

## 실행

항상 dry-run 으로 계산값을 먼저 보고 `--execute` 를 붙인다. 처음에는 팔 주변을 비우고 전원 스위치 가까이에서 한다.

```bash
# 계산 자체 검증 (ROS 불필요)
python3 omx_ik.py selftest

# 1. 이동만 (dry-run -> 실행)
python3 go_down.py --arm single --xyz 0.18 0.00 0.10 --t-pre 6 --t-down 5 --correct 2
python3 go_down.py --arm single --xyz 0.18 0.00 0.10 --t-pre 6 --t-down 5 --correct 2 --execute

# 2. 그리퍼만 (팔은 안 움직임). 값은 실측치로 바꿔서
#    omx_f.launch.py:
ros2 action send_goal /gripper_controller/gripper_cmd control_msgs/action/GripperCommand "{command: {position: <열림>, max_effort: 0.0}}"
#    omx_f_follower_ai.launch.py:
ros2 topic pub --once /leader/joint_trajectory trajectory_msgs/msg/JointTrajectory \
  "{joint_names: [gripper_joint_1], points: [{positions: [<열림>], time_from_start: {sec: 2}}]}"

# 3. 이동 + 잡기 + 들기 + 놓기 (한 사이클)
python3 go_down.py --arm single --xyz 0.18 0.00 0.04 --correct 2 \
  --grip --grip-open <열림> --grip-close <닫힘> --grip-current 200 \
  --lift-dz 0.05 --release --execute
#    omx_f_follower_ai.launch.py 면 --traj-topic /leader/joint_trajectory 추가

# 좌표 자동 수신 (다른 노드가 PointStamped 로 보냄). 반복 사이클이면 --release 를 붙인다.
#   --release 가 없으면 다음 좌표가 왔을 때 "하강 전 열기" 단계에서 들고 있던 것을 그 자리에 놓는다.
python3 go_down.py --arm single --listen /target_point --grip --grip-open <열림> --grip-close <닫힘> --lift-dz 0.05 --release --execute
ros2 topic pub --once /target_point geometry_msgs/msg/PointStamped "{header: {frame_id: link0}, point: {x: 0.18, y: 0.0, z: 0.04}}"

# 양팔 동시 하강 (네임스페이스 left/right)
python3 go_down.py --both --left-xyz X Y Z --right-xyz X Y Z --execute
```

### 잡기 동작의 순서와 판정

1. 시작할 때 그리퍼 모터의 **Operating Mode** 를 `get_dxl_data` 서비스로 읽어 5(Current-based Position) 인지 확인하고, `set_dxl_data` 서비스로 **Goal Current** 를 `--grip-current`(mA) 로 쓴다. 서비스가 없거나, 모드가 5 가 아니거나, 쓰기에 실패하면 그리퍼를 움직이기 전에 종료한다. `--grip-current 0` 을 주면 이 단계를 건너뛰고 모터에 이미 들어 있는 Goal Current 와 Current Limit 을 그대로 쓴다(xacro 기본 600). 옷은 150~250 에서 시작해 미끄러지면 올린다. 상한 600.
2. 그리퍼를 `--grip-open` 으로 열고, `/joint_states` 로 열림 근처에 도달한 것을 확인한다. 확인되지 않으면 하강하지 않는다.
3. 하강하고 `--correct N` 만큼 처짐을 보정한다.
4. `--grip-close` 로 닫는다. 액션 모드면 수락, 완료 status, 결과(reached_goal, stalled)를 확인한다(stalled 는 접촉으로 간주). 두 방식 모두 `/joint_states` 를 0.3 초 간격으로 읽어 연속 두 값의 차이가 0.01 rad 미만일 때의 위치를 쓴다. 안정되지 않으면 판정 불가로 처리하고 들지 않는다.
   - 열림 위치에서 거의 안 움직였으면 **닫히지 않음**(에러), 닫힘 값에 `--grip-empty-tol`(기본 0.05 rad) 이내로 도달했으면 **빈손**. 둘 다 들지 않고 그리퍼를 다시 열어 닫힘 목표를 지운다. 억지로 들려면 `--lift-anyway`.
   - 그 사이에서 멈췄으면 물체를 문 것으로 보고 `--lift-dz` 만큼 든다.
5. `--release` 가 있으면 들어 올린 뒤 다시 열고 열림을 확인한다. 없으면 닫힌 채(전류 제한 안에서) 유지된다.
6. 닫기나 들기 중에 Ctrl+C 를 누르거나 예외가 나면 그리퍼를 열고 종료한다. 열기 복구가 확인되지 않으면 에러를 찍고(`--listen` 이면 수신도 멈춤), 토크를 푸는 명령을 안내한다.
7. `--grip` 은 한 팔 모드 전용이다. `--both` 와 같이 쓰면 거부된다(두 팔은 실측값과 모터 설정이 다를 수 있음).
8. 모터를 리부트하거나 Wizard 로 설정을 바꿨으면 스크립트를 다시 시작한다. 모드와 전류 확인은 시작할 때 한 번만 한다.

### 주요 옵션

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--arm single\|left\|right` | single | 네임스페이스 없음 / left / right |
| `--traj-topic` | `/<ns>/arm_controller/joint_trajectory` | 팔 궤적 토픽. follower_ai 런치는 `/leader/joint_trajectory` |
| `--min-z` | 0.03 | TCP 최저 높이. 책상 z + 여유로 설정 |
| `--t-pre`, `--t-down`, `--t-lift` | 4, 3, 3 | 각 구간 이동 시간(s) |
| `--correct N` | 0 | 하강 후 처짐 보정 횟수. 2 권장 |
| `--grip-mode auto\|action\|traj` | auto | 그리퍼 전송 방식 |
| `--grip-current` | 200 | 닫기 전 Goal Current(mA). 0 이면 안 씀 |
| `--grip-id` | 16 | 그리퍼 Dynamixel ID |
| `--grip-limit LO HI` | open/close 사이 | 그리퍼 명령 허용 범위 추가 제한 |
| `--grip-empty-tol` | 0.05 | 빈손 판정 폭(rad) |
| `--lift-anyway` | 꺼짐 | 빈손이어도 듦 |
| `--release` | 꺼짐 | 든 뒤 그리퍼 열기 |
| `--yes` | 꺼짐 | Enter 확인 생략 |

## 안전

- 기본은 dry-run. `--execute` 없이는 아무것도 움직이지 않는다.
- 그리퍼는 `--grip-open` 과 `--grip-close` 사이로만 명령된다. 범위 밖 값은 잘라서 보내고 경고를 찍는다.
- 사용 중인 `open_manipulator_description/ros2_control/omx_f.ros2_control.xacro`(2026-06-26 커밋 기준)는 ID 16 에 `Shutdown 21`(과부하 보호 제외)과 `Goal Current 600` 을 쓴다. 하드스톱을 밀면 과부하 셧다운 없이 계속 민다. `--grip-current` 로 낮추고, 가능하면 xacro 의 `Shutdown` 을 `53` 으로 바꾼다.
- XL330(ID 14~16) 권장 공급 전압은 5.0 V(스펙 3.7~6.0 V)다. 2026-10-16 측정에서 한쪽 팔은 무부하 6.0 V, 급가감속 때 7.2 V 까지 올라가 Input Voltage 에러(Max Voltage Limit 7.0 V 초과)로 셧다운됐다. 멀티미터로 레일 전압을 확인하고 5.0 V 로 맞춘다.
- 좌표는 팔 베이스(`link0`) 기준이다. 카메라 좌표를 그대로 넣으면 엉뚱한 곳으로 간다.
- 토크가 풀린 상태에서는 명령이 실행되지 않는다. 이동 전에 토크를 켠다.
- 링크 간 충돌은 계산하지 않는다. 양팔 동시 동작은 목표 간격을 넉넉히 둔다.

## 검증 상태

- 실기(한 팔, 2026-10-11): 좌표 -> 이동 -> 수직 하강. `--correct 2` 로 TF(`tf2_echo`) 기준 z 오차 1 mm. 줄자로 잰 실제 손끝 위치와의 비교는 아직 없다.
- 그리퍼 잡기, 들기, `--listen`, 양팔 동시: 코드만 있고 실기 미검증. 그리퍼 모터(ID 16) 교체 후 위 순서대로 시험한다.
- 커스텀 그리퍼 끝 위치(`omx_ik.py` 의 `EE_OFFSET`)는 줄자 실측 전. 다르면 `python3 omx_ik.py check <실측 x y z> <q1 q2 q3 q4 q5>` 로 비교해 수정한다.

작성: Ahhyeon430
