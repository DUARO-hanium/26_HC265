#!/usr/bin/env bash
# v4l2loopback 가상 카메라 설치·로드 (WSL, 카메라 브리지용)
#
# 카메라 브리지(camera_bridge.sh)는 Windows에서 온 영상을 가상 카메라
# /dev/video10(front), /dev/video11(wrist)로 밀어넣고, lerobot-record가
# 그 장치를 일반 카메라처럼 읽는다. 이 스크립트는 그 가상 장치를 만든다.
#
# 주의: WSL 커널은 settings.md 1.3에서 직접 빌드한 커스텀 커널이므로
# apt의 v4l2loopback-dkms(배포판 헤더 대상)는 맞지 않는다. 반드시
# 같은 소스 트리(~/WSL2-Linux-Kernel)에 대고 빌드해야 한다.
#
# 사용법:
#   bash setup_v4l2loopback.sh          # 필요 시 빌드 후 모듈 로드
# 모듈은 WSL 재시작마다 다시 로드해야 한다 (이 스크립트 재실행이면 됨).

set -euo pipefail

KDIR="${DUARO_WSL_KERNEL_DIR:-$HOME/WSL2-Linux-Kernel}"
SRC_DIR="${DUARO_V4L2LOOPBACK_DIR:-$HOME/v4l2loopback}"
MODULE_OPTS="devices=2 video_nr=10,11 card_label=duaro_front,duaro_wrist exclusive_caps=1,1"

# 이미 로드되어 장치까지 있으면 끝
if [[ -e /dev/video10 && -e /dev/video11 ]] && lsmod | grep -q '^v4l2loopback'; then
    echo "정상: v4l2loopback 로드됨 (/dev/video10, /dev/video11)"
    exit 0
fi

# 커널 모듈 지원 확인
if ! grep -q '^CONFIG_MODULES=y' "/boot/config-$(uname -r)" 2>/dev/null \
   && ! zgrep -q '^CONFIG_MODULES=y' /proc/config.gz 2>/dev/null \
   && [[ ! -f "$KDIR/.config" || -z "$(grep '^CONFIG_MODULES=y' "$KDIR/.config" || true)" ]]; then
    echo "중단: 커널이 모듈 로딩(CONFIG_MODULES)을 지원하는지 확인 불가." >&2
    echo "  $KDIR/.config 에서 CONFIG_MODULES=y 확인 후 재시도." >&2
    exit 1
fi

# 빌드 (1회)
if [[ ! -f "$SRC_DIR/v4l2loopback.ko" ]]; then
    if [[ ! -d "$KDIR" ]]; then
        echo "중단: 커널 소스가 없습니다: $KDIR" >&2
        echo "  settings.md 1.3의 WSL 커널 빌드를 먼저 수행하거나," >&2
        echo "  경로가 다르면 DUARO_WSL_KERNEL_DIR로 지정하세요." >&2
        exit 1
    fi
    if [[ ! -f "$KDIR/Module.symvers" ]]; then
        echo "중단: $KDIR 가 빌드된 커널 트리가 아닙니다 (Module.symvers 없음)." >&2
        echo "  settings.md 1.3의 make 빌드가 완료된 트리여야 합니다." >&2
        exit 1
    fi
    if [[ ! -d "$SRC_DIR" ]]; then
        echo "v4l2loopback 소스 clone: $SRC_DIR"
        git clone --depth 1 https://github.com/umlaeute/v4l2loopback.git "$SRC_DIR"
    fi
    echo "커스텀 커널 트리에 대고 빌드: KERNEL_DIR=$KDIR"
    # v4l2loopback Makefile의 변수명은 KERNEL_DIR (KDIR은 혹시 모를 변형 대비 병기)
    make -C "$SRC_DIR" KERNEL_DIR="$KDIR" KDIR="$KDIR"
fi

# 로드
echo "모듈 로드: $MODULE_OPTS"
# shellcheck disable=SC2086
sudo insmod "$SRC_DIR/v4l2loopback.ko" $MODULE_OPTS 2>/dev/null || {
    # 이미 로드돼 있는데 장치 번호가 다른 경우 → 내리고 다시
    sudo rmmod v4l2loopback 2>/dev/null || true
    # shellcheck disable=SC2086
    sudo insmod "$SRC_DIR/v4l2loopback.ko" $MODULE_OPTS
}

test -e /dev/video10 && test -e /dev/video11 || {
    echo "중단: 모듈은 로드됐지만 /dev/video10,11 이 생기지 않았습니다." >&2
    exit 1
}
echo "완료: /dev/video10(front), /dev/video11(wrist) 준비됨"
