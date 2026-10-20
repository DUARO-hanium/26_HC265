# MoveItPy 초기화 문제 해결

## 문제

Python 스크립트에서 MoveItPy를 독립적으로 생성하면 "Failed to load planning pipelines from parameter server" 에러 발생. omx_f, omx_l 둘 다 동일하게 재현됨 (설정 파일 문제 아님).

## 원인

MoveItConfigsBuilder에서 `.robot_description()`, `.planning_pipelines()` 등을 개별 지정해도 MoveItPy 내부의 moveit_cpp 노드가 자체 파라미터로 다시 읽으려 시도하면서 실패.

## 해결

`.moveit_cpp(file_path=...)`로 별도 yaml 파일을 명시적으로 지정해야 함.

### moveit_cpp_config.yaml

```yaml
planning_scene_monitor_options:
  name: "planning_scene_monitor"
  robot_description: "robot_description"
  joint_state_topic: "/joint_states"
  attached_collision_object_topic: "/attached_collision_object"
  publish_planning_scene_topic: "/monitored_planning_scene"
  monitored_planning_scene_topic: "/monitored_planning_scene"
  wait_for_initial_state_timeout: 10.0

planning_pipelines:
  pipeline_names: ["ompl"]

plan_request_params:
  planning_attempts: 1
  planning_pipeline: ompl
  max_velocity_scaling_factor: 0.1
  max_acceleration_scaling_factor: 0.1
```

### 스크립트에서

```python
moveit_config = (
    MoveItConfigsBuilder("omx_l", package_name="omx_l")
    .moveit_cpp(file_path="/home/ap432/moveit_cpp_config.yaml")
    .to_moveit_configs()
    .to_dict()
)
moveit = MoveItPy(node_name="bag_insertion", config_dict=moveit_config)
```

## 추가로 확인된 것

`plan_cartesian_path()`는 이 MoveItPy 버전(Jazzy)의 PlanningComponent에 존재하지 않음. 대신 waypoint를 하나씩 `set_goal_state()` + `plan()` + `execute()`로 순차 실행하는 방식으로 우회.

`set_goal_state()`의 `pose_stamped_msg` 인자는 `Pose`가 아니라 `PoseStamped` 타입이어야 함 (헤더 포함).

## 참고 자료

- GitHub Issue: https://github.com/moveit/moveit2/issues/2657
