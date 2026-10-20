#!/usr/bin/env bash
set -eo pipefail

# ROS setup files may probe optional variables that are unset. Enable nounset
# only after sourcing the environment.
source /opt/ros/jazzy/setup.bash
set -u

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "usage: $0 UDP_PORT [CAMERA_NAME] [CAMERA_INFO_URL]" >&2
  exit 2
fi

udp_port=$1
camera_name=${2:-camera1}
camera_info_url=${3:-file://${HOME}/.ros/camera_info/camera1.yaml}
if [[ ! "$udp_port" =~ ^[0-9]+$ ]] || (( udp_port < 1024 || udp_port > 65535 )); then
  echo "invalid UDP port: $udp_port" >&2
  exit 2
fi
if [[ ! "$camera_name" =~ ^[a-zA-Z][a-zA-Z0-9_]*$ ]]; then
  echo "invalid camera name: $camera_name" >&2
  exit 2
fi

pipeline="udpsrc port=${udp_port} caps=\"application/x-rtp,media=(string)video,clock-rate=(int)90000,encoding-name=(string)JPEG,payload=(int)26\" ! rtpjitterbuffer latency=100 drop-on-latency=true ! rtpjpegdepay ! jpegparse"

exec ros2 run gscam gscam_node --ros-args \
  -r __node:="gscam_${camera_name}" \
  -r camera/image_raw/compressed:="/${camera_name}/image_raw/compressed" \
  -r camera/camera_info:="/${camera_name}/camera_info" \
  -p gscam_config:="$pipeline" \
  -p image_encoding:=jpeg \
  -p camera_name:="$camera_name" \
  -p camera_info_url:="$camera_info_url" \
  -p use_gst_timestamps:=false \
  -p sync_sink:=false \
  -p frame_id:="${camera_name}_optical_frame" \
  -p use_sensor_data_qos:=true
