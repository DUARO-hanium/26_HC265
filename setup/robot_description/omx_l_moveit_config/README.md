# omx_l_moveit_config

Leader(omx_l) 로봇의 MoveIt2 설정 패키지. MoveIt Setup Assistant로 생성함.

기존 open_manipulator_moveit_config 패키지에는 omx_f 등 Follower 계열 로봇 설정만 있고 Leader(omx_l)용이 없어서 별도 패키지로 생성.

## 구성
- `config/omx_l.srdf` — planning group(arm, gripper), end effector 정의
- `config/kinematics.yaml` — IK solver 설정
- `config/joint_limits.yaml` — 관절 속도/가속도 제한
- `config/ompl_planning.yaml` — OMPL planner 설정
  (waypoint 순차 plan() 실행에 사용, docs/06_bag_insertion_planning.md 참고)
- `launch/demo.launch.py` — RViz + MoveIt2 실행

## 사용법

### 단독 실행 (RViz + MoveIt2 확인용)
```bash
cd ~/ros2_ws
colcon build --packages-select omx_l
source install/setup.bash

source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
ros2 launch omx_l demo.launch.py
```

### 실물 로봇과 함께 사용

`rule_based/bag_insertion.py`에서 이 패키지를 참조함. 전체 실행 순서, 사전 준비 사항은 docs/06_bag_insertion_planning.md 참고.

## 생성 과정 및 트러블슈팅
자세한 생성 과정과 겪었던 에러들은 troubleshooting/omx_l_setup.md 참고.

## 알려진 이슈
- home 자세(joint2=-1.57, joint3=1.57, joint4=1.57)가 link0-link5 충돌을 일으킴. omx_f 값을 그대로 가져와서 발생. 실측 후 재설정 필요.
