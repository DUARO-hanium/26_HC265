# MoveIt2 + RViz 

## 환경 설정

> ⚠️ LeRobot 설치와는 별개로, ROS2 워크스페이스에 open_manipulator 레포가 추가로 필요함

ROS2 Jazzy, MoveIt2 설치:
```bash
sudo apt update
sudo apt install ros-jazzy-moveit ros-jazzy-ros2-control ros-jazzy-ros2-controllers
sudo apt install ros-jazzy-backward-ros
sudo apt install ros-jazzy-joint-state-publisher-gui
```

워크스페이스 생성:
```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone https://github.com/ROBOTIS-GIT/open_manipulator.git
cd ~/ros2_ws
colcon build --packages-select open_manipulator_description open_manipulator_moveit_config open_manipulator_bringup open_manipulator_teleop om_spring_actuator_controller
```

> ⚠️ 본인 워크스페이스 경로에 맞게 `~/ros2_ws` 부분 수정할 것
> ⚠️ 전체 `colcon build` 시 일부 패키지(om_gravity_compensation_controller 등) 빌드 실패할 수 있음 → 지금 단계에서는 무시 가능

---

## 실행

### 터미널 1
```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch open_manipulator_bringup omx_f.launch.py use_mock_hardware:=true
```

### 터미널 2 (터미널 1에서 `[joint_trajectory_executor]: All steps completed!` 메시지 뜬 후 실행)
```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch open_manipulator_moveit_config omx_f_moveit.launch.py
```

`You can start planning now!` 메시지가 뜨면 정상 실행.

---

## use_mock_hardware 옵션 설명

```
실제 OMX 모터 없이 가상 하드웨어로 컨트롤러를 동작시키는 옵션
→ 이게 없으면 arm_controller가 안 켜짐
→ MoveIt2가 명령을 보낼 곳이 없어서 Plan 실패
```

---

## RViz에서 테스트

```
1. MotionPlanning 패널 → Planning 탭
2. Goal State → "home" 선택 (random valid는 도달 불가능한 위치가 많아 비권장)
3. Plan 클릭
4. 경로 시각화 확인
```

---

## Note

- `description/launch/omx_f.launch.py`는 단순 시각화용 (controller 없음) → MoveIt2 Plan 안 됨
- `bringup/launch/omx_f.launch.py`를 써야 controller_manager가 같이 실행됨
- RViz Displays 패널 → MotionPlanning → Planned Path → **Loop Animation 체크 해제** 권장 (안 하면 Plan 결과가 무한 반복 재생됨)
- `<random valid>` Goal State는 실패 확률 높음 → SRDF에 정의된 `home`, `init` 같은 group_state 사용 권장

---

## 참고
- open_manipulator: https://github.com/ROBOTIS-GIT/open_manipulator
