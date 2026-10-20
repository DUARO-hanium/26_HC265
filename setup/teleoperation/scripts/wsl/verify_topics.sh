#!/usr/bin/env bash
set -euo pipefail

export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-30}
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_zenoh_cpp}
source /opt/ros/jazzy/setup.bash

topics=(
  /camera1/image_raw/compressed
  /camera2/image_raw/compressed
  /joint_states
  /leader/joint_trajectory
  /tf
)

for topic in "${topics[@]}"; do
  ros2 topic type "$topic" >/dev/null 2>&1 || {
    echo "실패: 토픽이 없습니다: $topic" >&2
    exit 1
  }
  echo "정상: $topic ($(ros2 topic type "$topic"))"
done

echo "필수 토픽이 모두 존재합니다. 녹화 전에 각 토픽 주기를 측정하세요."
