#!/usr/bin/env bash
# 카메라 브리지 (WSL 수신부): UDP/RTP MJPEG → 디코드 → v4l2loopback 가상 카메라
#
# Windows 쪽 windows/start_camera_sender.ps1 이 보낸 스트림을 받아
# /dev/video10(front) 또는 /dev/video11(wrist)로 출력한다.
# lerobot-record는 이 가상 장치를 일반 OpenCV 카메라로 읽는다
# (record.sh 에서 DUARO_CAM_FRONT=10 DUARO_CAM_WRIST=11).
#
# usbipd로 카메라를 WSL에 넘길 때 생기는 fps 붕괴(USB/IP isochronous 한계)를
# 우회하는 경로다. 수신 파이프라인 구조는 검증된
# omx-f-zenoh-data-collection/scripts/wsl/start_gscam_receiver.sh 를 따르되,
# 출력만 ROS 토픽 대신 v4l2loopback으로 바꿨다.
#
# 사용법 (카메라별 터미널 1개, 사전에 setup_v4l2loopback.sh 실행):
#   bash camera_bridge.sh front    # UDP 5000 → /dev/video10
#   bash camera_bridge.sh wrist    # UDP 5001 → /dev/video11
#   bash camera_bridge.sh <port> <device>   # 직접 지정도 가능

set -euo pipefail

case "${1:-}" in
    front) udp_port=5000; device=/dev/video10 ;;
    wrist) udp_port=5001; device=/dev/video11 ;;
    ''|-h|--help)
        echo "사용법: $0 front|wrist  또는  $0 UDP_PORT /dev/videoN" >&2
        exit 2 ;;
    *)
        udp_port=$1
        device=${2:-}
        [[ "$udp_port" =~ ^[0-9]+$ ]] && (( udp_port >= 1024 && udp_port <= 65535 )) || {
            echo "잘못된 UDP 포트: $udp_port" >&2; exit 2; }
        [[ -n "$device" ]] || { echo "장치 경로 필요 (예: /dev/video10)" >&2; exit 2; }
        ;;
esac

command -v gst-launch-1.0 >/dev/null || {
    echo "중단: GStreamer가 없습니다. 설치:" >&2
    echo "  sudo apt-get install -y gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad" >&2
    exit 1
}
test -e "$device" || {
    echo "중단: $device 가 없습니다. 먼저 실행: bash setup_v4l2loopback.sh" >&2
    exit 1
}

echo "수신 시작: UDP $udp_port → $device (종료: Ctrl+C)"
# jitterbuffer: 로컬 vEthernet이라 50ms면 충분, 늦은 프레임은 정체 대신 드랍
exec gst-launch-1.0 -v \
    udpsrc port="$udp_port" \
        caps="application/x-rtp,media=(string)video,clock-rate=(int)90000,encoding-name=(string)JPEG,payload=(int)26" \
    ! rtpjitterbuffer latency=50 drop-on-latency=true \
    ! rtpjpegdepay ! jpegdec ! videoconvert \
    ! video/x-raw,format=YUY2 \
    ! v4l2sink device="$device" sync=false
