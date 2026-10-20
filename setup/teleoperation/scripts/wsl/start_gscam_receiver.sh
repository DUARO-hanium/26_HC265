#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "사용법: $0 CONTAINER CAMERA_NAME UDP_PORT" >&2
  exit 2
fi

container=$1
camera_name=$2
udp_port=$3
[[ "$camera_name" =~ ^camera[0-9]+$ ]] || {
  echo "잘못된 카메라 이름: $camera_name" >&2
  exit 2
}
[[ "$udp_port" =~ ^[0-9]+$ ]] || {
  echo "잘못된 UDP 포트: $udp_port" >&2
  exit 2
}

pipeline="udpsrc port=${udp_port} caps=\"application/x-rtp,media=(string)video,clock-rate=(int)90000,encoding-name=(string)JPEG,payload=(int)26\" ! rtpjitterbuffer latency=100 drop-on-latency=true ! rtpjpegdepay ! jpegparse"

docker exec -d "$container" bash -lc "
  source /opt/ros/jazzy/setup.bash
  source /root/ros2_ws/install/setup.bash
  export ROS_DOMAIN_ID=30
  export RMW_IMPLEMENTATION=rmw_zenoh_cpp
  exec ros2 run gscam gscam_node --ros-args \
    -r __node:=gscam_${camera_name} \
    -r camera/image_raw/compressed:=/${camera_name}/image_raw/compressed \
    -r camera/camera_info:=/${camera_name}/camera_info \
    -p gscam_config:='$pipeline' \
    -p image_encoding:=jpeg \
    -p camera_name:=${camera_name} \
    -p use_gst_timestamps:=false \
    -p sync_sink:=false \
    -p frame_id:=${camera_name}_optical_frame \
    -p use_sensor_data_qos:=true
"

echo "$container 안에서 $camera_name 수신기를 UDP $udp_port 포트로 시작했습니다."
