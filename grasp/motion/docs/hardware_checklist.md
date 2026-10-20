# 로봇 점검 가이드 (시연 전에 이 순서대로)

실제 로봇에서 "좌표를 주면 팔이 그 위로 가서 내려가는가"를 확인하는 문서임.
각 단계에 **무엇을 보는지 / 어떻게 하는지 / 어떻게 되면 OK인지**를 적어 둠.

- 좌표는 전부 **팔 밑동(`link0`) 기준, 단위 m**. 팔이 한 대면 그 팔의 밑동이 원점임.
- `--execute` 를 붙이지 않으면 로봇은 **절대 안 움직임** (계산만 출력).
- 처음 움직일 땐 팔 주변을 비우고, 손은 전원 스위치 가까이에 둠.
- 한 단계가 실패하면 다음 단계로 넘어가지 않음.

## 지금까지 된 것 / 안 된 것 (2026-10-11 기준)

| 단계 | 무엇을 확인하나 | 결과 |
|---|---|---|
| 1 | 로봇이 켜지고 명령을 받을 준비가 되었나 | OK |
| 2 | 손으로 팔을 움직일 수 있나 | OK |
| 3 | 코드가 아는 손끝 위치 = 실제 손끝 위치인가 | 거의 OK (줄자 확인 남음) |
| 4 | 좌표를 주면 팔이 그쪽으로 가서 내려가나 | OK |
| 5 | 도착한 위치가 목표와 몇 mm 차이인가 | OK (`--correct 2` 쓰면 1 mm) |
| 6 | 책상 높이(z)를 알고 있나 | 아직 |
| 7 | 다른 프로그램이 보낸 좌표를 받아서 움직이나 | 아직 |
| 8 | 그리퍼가 열리고 닫히나 | **안 됨 (모터 에러 `0x10`, 조사 중)** |
| 9 | 잡고 들어 올리나 | 아직 (8번이 먼저) |
| 10 | 두 팔이 동시에 움직이나 | 아직 |
| 11 | 팀원의 좌표 변환 결과와 이어지나 | 아직 |
| 12 | 잘 갔던 좌표를 기록해 두었나 | 일부 |

시연에 쓸 수 있는 것은 **1~5번 (좌표 -> 이동 -> 수직 하강)** 까지임.

## 먼저 알아둘 것

팔이 닿는 범위: 팔 밑동에서 수평으로 약 0.26 m 이내. 목표 위 6 cm 지점을 먼저 거치므로 위쪽 가장자리 목표는 "도달 불가"가 나올 수 있음. 그땐 z를 낮추거나 팔에 더 가깝게 놓음.

| 수평 거리 | 수직 하강 가능한 높이 z (계산값) |
|---|---|
| 0.10 m | -0.28 ~ +0.22 |
| 0.18 m | -0.23 ~ +0.18 |
| 0.22 m | -0.19 ~ +0.14 |
| 0.26 m | -0.10 ~ +0.06 |
| 0.30 m | 불가 |

## 단계별 방법

### 1. 로봇이 켜졌는지
- 하는 일: 터미널 1에서 launch 를 켜 두고, 터미널 2에서 아래를 실행함.
```bash
ros2 control list_controllers
ros2 topic list | grep trajectory
ros2 topic echo /joint_states --once --field position
```
- OK 기준: `arm_controller`, `joint_state_broadcaster` 가 `active`. 토픽 `/arm_controller/joint_trajectory` 가 보임.
- 실측: 한 팔은 이름 앞 네임스페이스 없음. `joint_states` 순서는 `gripper_joint_1, joint1~5`.
- 이름이 다르면 `go_down.py` 의 `--ns-*`, `--joint-prefix` 옵션으로 맞춤.

### 2. 손으로 팔 움직이기
- 왜: 손끝을 원하는 곳에 대고 좌표를 읽을 때 필요함.
- 방법: launch 를 Ctrl+C 로 끄면 토크가 꺼져 손으로 움직일 수 있음. 다시 켜면 그 자세로 토크가 걸림.

### 3. 코드가 아는 손끝 위치 = 실제 손끝 위치
- 하는 일: 같은 자세에서 "코드 계산값"과 "로봇이 알려주는 값"을 비교함.
```bash
timeout 5 ros2 run tf2_ros tf2_echo link0 end_effector_link
python3 omx_ik.py fk <q1> <q2> <q3> <q4> <q5>      # q는 joint_states 의 joint1~5 값
```
- OK 기준: 두 값 차이 10 mm 이하.
- 실측: 코드 `[0.0386, -0.0018, 0.0184]`, 로봇 `[0.039, -0.002, 0.018]` (1 mm 이내).
- 남은 것: 로봇이 알려주는 값은 설계도 기준이라, **커스텀 그리퍼 끝을 줄자로 직접 재서** 한 번 더 비교해야 함.

### 4. 좌표를 주면 그 위로 가서 내려가는지
```bash
cd ~/omx_down
python3 go_down.py --arm single --xyz 0.18 0.00 0.10 --t-pre 6 --t-down 5 --correct 2            # 계산만
python3 go_down.py --arm single --xyz 0.18 0.00 0.10 --t-pre 6 --t-down 5 --correct 2 --execute  # 실제 이동
```
- 동작: 목표 6 cm 위로 이동 -> 수직으로 하강.
- OK 기준: 예상한 방향으로 움직이고, 그리퍼가 아래를 향한 채 내려감.
- 이동이 끝나면 `Enter` 로 진행. 로그의 `SUCCEEDED` 는 믿지 말고 5번처럼 실제 위치로 확인함.

### 5. 목표와 실제 위치 차이
- 하는 일: 4번 직후 `tf2_echo` 로 손끝 위치를 읽어 목표와 비교함.
- OK 기준: 10 mm 이내.

| 목표 | 처짐 보정 | 실제 도착 | z 차이 | 기울기 |
|---|---|---|---|---|
| (0.18, 0, 0.10) | 없음 | (0.179, -0.003, 0.087) | -13 mm | 3.8° |
| (0.12, 0, 0.08) | 없음 | (0.118, -0.002, 0.075) | -5 mm | 2.0° |
| (0.18, 0, 0.10) | `--correct 2` | (0.179, -0.002, 0.099) | -1 mm | 0.5° |

- 왜 낮게 가나: 어깨 모터가 중력 때문에 명령보다 약 3° 덜 돌아감. 멀리 뻗을수록 더 큼.
- 해결: `--correct 2` 를 붙이면 실제 각도를 읽어 부족한 만큼 한 번 더 보냄. **항상 붙이는 것을 권장.**

### 6. 책상 높이(z)
- 왜: 책상보다 낮은 z로 가면 팔이 책상을 칠 수 있음.
- 방법: 몸체 높이를 시연 때 쓸 값으로 고정함 -> 팔 끝을 책상에 살짝 대고 `tf2_echo` 의 z 를 읽음 (팔마다).
- 이후: 이 값 + 여유를 `--min-z` 로 넣으면 그보다 낮은 목표는 거부됨. **몸체 높이를 바꾸면 다시 측정.**

### 7. 다른 프로그램이 보낸 좌표 받기
```bash
# 터미널 A: 대기
python3 go_down.py --arm single --listen /target_point --execute
# 터미널 B: 좌표 보내기 (시험용)
ros2 topic pub --once /target_point geometry_msgs/msg/PointStamped \
  "{header: {frame_id: link0}, point: {x: 0.20, y: 0.0, z: 0.10}}"
```
- OK 기준: 받았다는 로그 후 팔이 내려감. 닿지 않는 좌표를 보내면 죽지 않고 "건너뜀"만 출력.

### 8. 그리퍼 열기/닫기 (미해결)
- 하는 일: `gripper_joint_1` 에 값을 보내 열림/닫힘을 확인함. 그리퍼 시험은 `omx_f_follower_ai.launch.py` 로 함 (명령 토픽 `/leader/joint_trajectory`).
- 현재 문제: 컨트롤러는 목표를 내는데 **모터가 따라가지 않고, 모터에 에러 `0x10` 이 켜짐.** 자세한 내용은 맨 아래 "그리퍼 조사 기록".
- 시험할 때는 **작은 이동부터**, 범위(아래 기록 표) 안의 값만 보냄. 에러가 켜지면 Wizard 로 Reboot 한 뒤 다시 시작함.

### 9. 잡고 들어 올리기
```bash
python3 go_down.py --arm single --xyz <x y z> --lift-dz 0.05 \
  --grip --grip-open <값> --grip-close <값> --execute
```
- OK 기준: 옷을 잡고 수직으로 들어 올림. 미끄러짐과 모터 과부하 알람을 같이 봄.
- 8번이 되어야 시험 가능함.

### 10. 두 팔 동시
```bash
python3 go_down.py --both --left-xyz <x y z> --right-xyz <x y z> --execute
```
- OK 기준: 두 팔이 다 움직이고 통신 오류(`SYNC_READ_FAIL`) 없음. 실패하면 팔마다 터미널을 따로 열어 실행.

### 11. 팀원의 좌표 변환과 이어지기
- 확인할 것: 변환 결과가 **어느 팔의 `link0` 기준**인지.
- 방법: 책상의 한 점에 팔 끝을 대고 `tf2_echo` 값을 읽음 -> 그 점의 화면 좌표를 변환에 넣은 결과와 비교함.
- OK 기준: 1~2 cm 이내. 크게 다르면 기준 팔이 다르거나 보정 문제.

### 12. 잘 갔던 좌표 기록
- 잘 갔던 위치 5곳 정도의 (x, y, z)와 관절각을 아래 "기록" 표에 적어 둠. 변환이 안 될 때 `--xyz` 로 직접 넣어 시연할 수 있음.

## 팀원 변환이 안 될 때 (대체 경로)
화면 (u,v) -> 책상 (x,y) 변환표를 직접 만드는 방법임. 관련 파일은 `coord_conversion/` 폴더에 있음.
1. 옷을 놓을 영역을 감싸게 6~9곳에 십자 표시. 각 표시마다 화면 (u,v)와 팔 끝 (x,y)를 읽어 `calib_<arm>.csv` 에 적음 (형식: `coord_conversion/examples/calib_points_example.csv`).
2. `python3 coord_conversion/homography_map.py fit --csv calib_left.csv --table-z <6번에서 읽은 z> --out calib_left.json`
3. 기준점이 아닌 3~4곳으로 검증: `python3 coord_conversion/homography_map.py check --calib calib_left.json --csv test_points.csv` -> 평균 10 mm 이하
4. `python3 coord_conversion/watch_and_go.py --json latest_result.json --calib-left calib_left.json --calib-right calib_right.json --once` (계산 확인 후 `--execute`)

## 막혔을 때
- 위치가 몇 cm 어긋남 -> 기준점을 늘려 다시 측정, 옷 놓는 영역을 좁힘.
- 두 팔 통신 오류 -> 팔마다 터미널을 따로 열어 launch 하고 `--arm left/right` 로 각각 실행.
- "도달 불가"가 자주 뜸 -> 옷을 팔 밑동에서 0.26 m 안쪽에 놓음.
- 하강했는데 z가 목표보다 낮음 -> `--correct 2` 를 붙임.

## 기록 (측정 후 채움)

| 항목 | 값 |
|---|---|
| 명령 토픽 / 네임스페이스 | `/arm_controller/joint_trajectory` / 없음 (한 팔) |
| 관절 이름 | `joint1~5` (+ `gripper_joint_1`) |
| 손끝 위치 줄자 실측 (`EE_OFFSET`) | |
| 책상 z (왼팔 / 오른팔) | |
| 그리퍼 열림 / 닫힘 (모터 위치 값) | 열림 끝 1775, 닫힘 끝 639 (닫을수록 작아짐). 안전 구간 720 ~ 1695 |
| 그리퍼 열림 / 닫힘 (ROS 각도) | 손으로 잰 값 -0.603 / +0.856. 모터 위치 값과의 대응은 재측정 필요 |
| 두 팔 밑동 간격 (x y z yaw) | |
| 좌표 변환 기준 팔 | |

## 그리퍼 조사 기록 (2026-10-11, 미해결)

**한 줄 요약**: 컨트롤러는 그리퍼 목표(0.2)를 정상으로 내는데 모터가 따라가지 않고, 모터에 에러 `0x10`(Hardware Error Status = 16)이 켜짐. 팔 하강과는 별개 문제임.

**launch 별 차이**
- `omx_f.launch.py`: 그리퍼 액션(`/gripper_controller/gripper_cmd`)이 목표를 받아도 실행하지 않음. `ros2 control list_hardware_interfaces` 에서 그리퍼가 `[unavailable] [unclaimed]`.
- `omx_f_follower_ai.launch.py`: 그리퍼가 `arm_controller` 의 6번째 관절로 들어가 `[available] [claimed]`. 팔 명령 토픽이 `/leader/joint_trajectory` 로 바뀌고, 켜도 팔이 초기 자세로 움직이지 않음.

**확인된 사실**
- `controller_state`: reference 0.2, feedback -0.457, error 0.657 rad. 컨트롤러는 목표를 내지만 모터가 못 따라감.
- ID 16 (XL330-M288): 열림 끝 1775 (156.0°), 닫힘 끝 639 (56.2°). Operating Mode 5, Profile Velocity 50, 입력 전압 6.0 V (정지 시).
- 에러 `0x10` 은 비트 4. XL330 에서 Electrical Shock(전원/전류 부족 또는 회로 문제)으로 알고 있음. **정확한 이름은 매뉴얼로 재확인 필요.** 에러가 켜지면 토크가 꺼지고, Reboot 전에는 토크를 켤 수 없음.
- Wizard 로 범위 안 위치를 직접 주면 에러 없이 움직임. Wizard "중앙"(2048, 열림 끝 바깥)을 누르면 에러가 켜짐.
- 에러가 났을 때 상태 표시줄 전압이 4.9 V 까지 내려간 적이 있음 (정지 시 6.0 V).
- 컨트롤러의 `SUCCEEDED` 결과는 믿으면 안 됨. `joint_states`, `controller_state` 로 확인함.

**원인 후보 (확정 못 함)**
1. 한계 밖 목표를 보내 벽을 밀게 됨 (Wizard "중앙", ROS -0.90).
2. ROS 가 모터에 쓰는 방식이 Wizard 와 다름 (이동 폭이 큼, 각도와 모터 위치 값의 대응 어긋남).
3. 힘을 쓸 때 전원이 처짐 (6.0 V → 4.9 V). 어댑터, 커넥터, 케이블 확인 필요.
4. launch 상태 꼬임 (처음에는 launch 중에도 손가락이 자유로웠고, 전원을 껐다 켠 뒤에는 토크가 걸림).

**다음**
- Reboot 후 작은 이동(-0.457 → -0.30)부터 ROS 로 시험하고, 에러가 켜지는지 Wizard 로 확인함.
- 에러 이름을 매뉴얼에서 확인, 전원 어댑터 정격 확인, 다른 팔의 같은 모터로 비교함.
- 각도(rad)와 모터 위치 값의 대응을 재측정한 뒤 `--grip-open`, `--grip-close` 값을 확정함.
- 안 되면 팀원/교수님께 그리퍼 점검을 요청함.
