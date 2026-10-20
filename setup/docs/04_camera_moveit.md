# 카메라 연동 + MoveIt2

## 환경 설치

```bash
sudo apt install ros-jazzy-usb-cam
```

---

## 1단계 - 카메라 연결 및 확인

WSL2 USB 연결:
```powershell
# Windows PowerShell 관리자 권한
usbipd list

usbipd attach --wsl --busid <카메라 BUSID>
```

권한 설정:
```bash
sudo chmod 666 /dev/video0
sudo chmod 666 /dev/video1
```

> ⚠️ WSL 재시작할 때마다 usbipd attach와 chmod 다시 해야 함

카메라 실행:
```bash
source /opt/ros/jazzy/setup.bash
ros2 run usb_cam usb_cam_node_exe --ros-args \
  -p pixel_format:=mjpeg2rgb \
  -p image_width:=640 \
  -p image_height:=480
```

화면 확인:
```bash
ros2 run rqt_image_view rqt_image_view
```
> 열리면 상단 드롭다운에서 `/camera/image_raw` 선택

---

## 2단계 - goal 좌표 찾기

### 방법 1 — 텔레오퍼레이션(권장)
```
1. Leader 손으로 움직여서 Follower를 봉지 앞까지 이동
2. 터미널 3에서 출력되는 translation x, y, z 값 기록
3. 이 값을 3단계 Python 스크립트 goal 좌표로 사용
```

<br>**터미널 1 - 로봇 실행**
```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch open_manipulator_bringup omx_f.launch.py port_name:=/dev/ttyACM0
```

**터미널 2 - 텔레오퍼레이션 실행**
```bash
conda activate lerobot
python -m lerobot.teleoperate \
    --robot.type=omx_follower \
    --robot.port=/dev/ttyACM0 \
    --robot.id=omx_follower_arm \
    --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}}" \
    --teleop.type=omx_leader \
    --teleop.port=/dev/ttyACM1 \
    --teleop.id=omx_leader_arm \
    --display_data=true
```

**터미널 3 - 좌표 읽기**
```bash
source /opt/ros/jazzy/setup.bash
ros2 run tf2_ros tf2_echo world end_effector_link
```

출력 예시:
```
translation:
  x: 0.25
  y: 0.0
  z: 0.15
rotation:
  x: 0.0
  y: 0.707
  z: 0.0
  w: 0.707
```

> translation 값 → 3단계 스크립트 position x, y, z에 입력
> <br>rotation 값 → orientation 설정 시 x, y, z, w에 입력

---

### 방법 2 — RViz 마커로 좌표 찾기

실제 로봇 없이 근사값을 얻을 때 사용. 실제 봉지 위치와 오차 있을 수 있음.

터미널 1, 2 실행은 03_moveit_rviz.md 참고.

```
1. RViz 3D 뷰에서 end effector 부분에
   빨강/파랑/초록 원 마커 보임
2. 마우스로 마커를 끌어서 봉지가 있을 위치로 이동
3. Plan 클릭해서 경로 계획 확인
4. 좌표 읽기:
```

```bash
source /opt/ros/jazzy/setup.bash
ros2 run tf2_ros tf2_echo world end_effector_link
```

---

### 방법 3 — 카메라로 자동 감지 (현재 불가)

현재 카메라(720P USB 2.0 UVC)는 RGB only라 depth 정보 없음.

**ArUco 마커 활용**
```
봉지에 ArUco 마커 부착
→ 카메라가 마커 크기와 각도로 거리 추정 가능
→ 3D 좌표 계산 가능
→ goal 좌표로 자동 전달
```

```bash
sudo apt install ros-jazzy-ros2-aruco
```

> 구현 복잡도가 높아서 현재 단계에서는 방법 1, 2 사용 권장

---

### 방법 4 — SRDF group_state로 저장

원하는 자세를 미리 이름 붙여 저장해두는 방법:

```
open_manipulator_moveit_config/config/omx_f/omx_f.srdf 파일에
원하는 자세를 group_state로 추가

예:
<group_state name="bag_front" group="arm">
  <joint name="joint1" value="0.5"/>
  <joint name="joint2" value="-1.0"/>
  ...
</group_state>
```

저장 후 MoveIt2에서 `bag_front`로 바로 호출 가능.

---

## 3단계 - MoveIt2 Python 스크립트로 자동 실행

> 2단계에서 기록한 x, y, z 값을 아래 스크립트에 넣으면
> 매번 텔레오퍼레이션 없이 자동으로 해당 위치로 이동

<br>**터미널 1 - 로봇 실행**
```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch open_manipulator_bringup omx_f.launch.py port_name:=/dev/ttyACM0
```

**터미널 2 - MoveIt2 실행**
```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch open_manipulator_moveit_config omx_f_moveit.launch.py
```

**스크립트 작성 및 실행**
```python
# move_to_pose.py
import rclpy
from moveit.planning import MoveItPy
from geometry_msgs.msg import Pose

def main():
    rclpy.init()
    moveit = MoveItPy(node_name="move_to_pose")
    arm = moveit.get_planning_component("arm")

    goal_pose = Pose()

    # 위치 (2단계 tf2_echo translation 값으로 교체)
    goal_pose.position.x = 0.0
    goal_pose.position.y = 0.0
    goal_pose.position.z = 0.0

    # 방향 (2단계 tf2_echo rotation 값으로 교체)
    # end effector가 봉지에 접근하는 방향이 중요한 경우 설정
    goal_pose.orientation.x = 0.0
    goal_pose.orientation.y = 0.0
    goal_pose.orientation.z = 0.0
    goal_pose.orientation.w = 1.0

    arm.set_goal_state(
        pose_stamped_msg=goal_pose,
        pose_link="end_effector_link"
    )
    arm.plan()
    arm.execute()

if __name__ == '__main__':
    main()
```

> orientation 없이 position만 설정하면 MoveIt2가 도달 가능한 방향을 자동으로 선택.
> orientation을 자유롭게 두고 싶으면 `goal_pose.orientation` 부분 삭제 가능.

```bash
python3 move_to_pose.py
```

> ⚠️ 스크립트 실행 전 터미널 1, 2가 모두 실행 중이어야 함

---

## Note
- 카메라: 720P USB 2.0 UVC (OMX AI 내장)
- 봉지 위치가 고정된 경우에만 해당 방법 유효

---

## 참고
- usb_cam: https://github.com/ros-drivers/usb_cam
- open_manipulator: https://github.com/ROBOTIS-GIT/open_manipulator
- ArUco: https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html
