#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env
load_profile_env
require_running_container
pose_name="${1:-commissioning_start_pose.interior.json}"
[[ "$pose_name" == "$(basename "$pose_name")" && "$pose_name" == *.json ]] || {
  echo "Pose must be a JSON basename inside the selected profile" >&2; exit 2;
}
pose_host="$(profile_host_dir)/$pose_name"
require_file "$pose_host"
limits_host="$(profile_host_dir)/safety_limits.audited.json"
require_file "$limits_host"
[[ -t 0 && -t 1 ]] || { echo "Run from an interactive terminal" >&2; exit 2; }

"$PROJECT_ROOT/scripts/run_container_preflight.sh" --duration 30 --min-rate 25 \
  --warn-dxl-gap 0.12 --max-dxl-gap 0.50 --max-dxl-loss-fraction 0.20
read -r -p "Clear the workspace, support the arm, then type MOVE TO PROFILE START: " answer
[[ "$answer" == "MOVE TO PROFILE START" ]] || exit 2

"$PROJECT_ROOT/scripts/prepare_container_runtime.sh" >/dev/null
pose_container="$(profile_container_dir)/$pose_name"
limits_container="$(profile_container_dir)/safety_limits.audited.json"
docker exec -it "$OMX_CONTAINER" bash -lc "
  source '$ROS_SETUP'; source /root/ros2_ws/install/setup.bash
  export ROS_DOMAIN_ID='$ROS_DOMAIN_ID' RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  '$OMX_SHARED_CONTAINER/venv/bin/python' - '$pose_container' '$limits_container' <<'PY'
import json, sys
import math
import rclpy
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionClient
from trajectory_msgs.msg import JointTrajectoryPoint

names = ['joint1','joint2','joint3','joint4','joint5','gripper_joint_1']
cfg = json.load(open(sys.argv[1], encoding='utf-8'))
limits = json.load(open(sys.argv[2], encoding='utf-8'))
if set(cfg.get('positions', {})) != set(names):
    raise ValueError('pose must contain exactly six canonical joints')
for name in names:
    value = float(cfg['positions'][name])
    if not math.isfinite(value):
        raise ValueError(f'non-finite pose: {name}')
    if name not in limits or not float(limits[name]['min']) <= value <= float(limits[name]['max']):
        raise ValueError(f'pose outside audited limit: {name}={value}')
rclpy.init(); node = rclpy.create_node('move_to_profile_pose')
client = ActionClient(node, FollowJointTrajectory, '/arm_controller/follow_joint_trajectory')
if not client.wait_for_server(timeout_sec=10): raise RuntimeError('controller action server unavailable')
goal = FollowJointTrajectory.Goal(); goal.trajectory.joint_names = names
point = JointTrajectoryPoint(); point.positions = [float(cfg['positions'][n]) for n in names]
duration = float(cfg.get('trajectory_duration_s', 12)); point.time_from_start.sec = int(duration)
point.time_from_start.nanosec = int((duration-int(duration))*1e9); goal.trajectory.points=[point]
future = client.send_goal_async(goal); rclpy.spin_until_future_complete(node, future)
handle = future.result()
if not handle or not handle.accepted: raise RuntimeError('pose goal rejected')
result = handle.get_result_async(); rclpy.spin_until_future_complete(node, result)
if result.result().result.error_code != 0: raise RuntimeError(result.result().result.error_string)
print('PROFILE_POSE_REACHED')
node.destroy_node(); rclpy.shutdown()
PY
"
