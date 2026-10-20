#!/usr/bin/env bash
# lerobot-calibrate 래퍼
# 사용법: bash calibrate.sh {follower|leader}

set -e

TARGET="${1:-}"

case "$TARGET" in
  follower)
    lerobot-calibrate \
      --robot.type=omx_follower \
      --robot.port=/dev/ttyACM0 \
      --robot.id=omx_follower_arm
    ;;
  leader)
    lerobot-calibrate \
      --teleop.type=omx_leader \
      --teleop.port=/dev/ttyACM1 \
      --teleop.id=omx_leader_arm
    ;;
  *)
    echo "사용법: bash calibrate.sh {follower|leader}"
    exit 1
    ;;
esac

# TODO: 완료 후 결과 JSON을 이 폴더에 날짜 태그로 사본 저장
