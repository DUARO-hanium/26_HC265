# OpenManipulator-X ROS 2 Control Scripts

OpenManipulator-X 제어를 위한 파이썬 스크립트 모음.

---

## 📜 스크립트 구성 및 역할 Overview

- **`pick_and_place.py` (메인 통합 스크립트):**  
  역역학(IK) 계산, 관절 이동, 그리퍼 제어를 하나로 묶은 메인 코드입니다. 실행 시 `[1] 그리퍼 열기 -> [2] (X,Y,Z) 위치 이동 -> [3] 그리퍼 닫기(집기)` 시퀀스가 순차적으로 진행됩니다.
- **`move_to_xyz.py` (단일 좌표 이동):**  
  목표 (X, Y, Z) 좌표를 입력받아 역역학(IK)을 계산하고, 그리퍼 동작 없이 로봇 팔만 해당 위치로 이동시킵니다.
- **`gripper_control.py` (그리퍼 개별 제어):**  
  그리퍼만 따로 여닫거나 특정 위치값으로 제어할 때 사용합니다. (`open`, `close` 또는 수치값 입력)
- **`go_home.py` (원점/초기 포즈 복귀):**  
  모든 관절 각도를 `0.0`으로 맞추어 로봇을 초기 Home 포즈로 복귀시킵니다.

---

## 🛠️ 요구 사항 (Prerequisites)
- ROS 2 (Humble / Jazzy)
- OpenManipulator-X (`open_manipulator_bringup`)
- 포트 설정: `/dev/ttyACM0` (port 번호 확인 필요) 

---

## 📐 좌표(X, Y, Z) 구하는 방법

로봇 베이스 중앙 바닥면이 기준점 `(0.0, 0.0, 0.0)`입니다. (단위: 미터 `m`)

### [방법 1] 좌표를 직접 지정할 때 (임의 설정)
로봇의 가동 범위를 고려하여 권장 범위 내에서 좌표를 임의 지정합니다.
- **X (앞뒤 거리):** `0.12` ~ `0.25`m (추천 기본값: `0.20`)
- **Y (좌우 거리):** `-0.15` ~ `0.15`m (왼쪽 `+`, 오른쪽 `-`, 중앙 `0.0`)
- **Z (높이):** `0.03` ~ `0.20`m (바닥 기준 위쪽)

### [방법 2] 실제 물체 위치를 측정할 때 (Hand-Teaching / 토크 OFF)
1. **모터 토크 끄기 (손으로 유연하게 이동 가능):**
   ```bash
   ros2 service call /dynamixel_hardware/set_dxl_torque std_srvs/srv/SetBool "{data: false}"
   ```
2. **손으로 로봇 팔을 그리퍼가 물체를 집을 정확한 위치까지 이동**
3. **현재 위치의 3D 좌표 출력 및 메모:**
   ```bash
   ros2 topic echo /kinematics_pose --once
   ```
   *(출력 결과 중 `pose.position.x`, `y`, `z` 값 메모)*
4. **모터 토크 다시 켜기:**
   ```bash
   ros2 service call /dynamixel_hardware/set_dxl_torque std_srvs/srv/SetBool "{data: true}"
   ```

---

## 🚀 실행 방법 (Usage)

### 1. 하드웨어 드라이버 실행 (터미널 1)
```bash
sudo chmod 666 /dev/ttyACM0
ros2 run rmw_zenoh_cpp rmw_zenohd
ros2 launch open_manipulator_bringup omx_f.launch.py usb_port:=/dev/ttyACM0
```

### 2. 메인 통합 시퀀스 실행 (터미널 2)
> 💡 **`pick_and_place.py`는 모든 동작이 통합된 메인 스크립트입니다.**  
> 실행 시 **[1] 그리퍼 미리 열기 $\rightarrow$ [2] 입력한 (X, Y, Z) 목표 위치로 이동 $\rightarrow$ [3] 그리퍼 닫기(물체 집기)** 과정이 순차적으로 자동 실행됩니다.

#### 🔹 [경우 A] 방법 1 적용 (임의 좌표 입력 시)
앞으로 20cm, 중앙, 높이 15cm 지점의 물체를 집을 때:
```bash
python3 src/scripts/pick_and_place.py 0.20 0.00 0.15
```

#### 🔹 [경우 B] 방법 2 적용 (티칭 모드로 구한 실측 좌표 입력 시)
위의 [방법 2]에서 메모한 `x`, `y`, `z` 값을 순서대로 입력합니다.  
*(예시: 메모한 값이 x=0.18, y=-0.05, z=0.08인 경우)*
```bash
python3 src/scripts/pick_and_place.py 0.18 -0.05 0.08
```

---

### 3. 기타 개별 테스트 스크립트
```bash
# Home 포즈 복귀 (0,0,0,0)
python3 src/scripts/go_home.py

# 단일 좌표 이동 (그리퍼 동작 없이 arm 위치 이동만 테스트)
python3 src/scripts/move_to_xyz.py 0.20 0.00 0.15

# 그리퍼 동작만 개별 테스트
python3 src/scripts/gripper_control.py open
python3 src/scripts/gripper_control.py close
```
