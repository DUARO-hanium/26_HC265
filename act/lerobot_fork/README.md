# lerobot_fork — 팀 fork LeRobot 변경분

`https://github.com/DUARO-hanium/lerobot` (`feature-omx-devel` 브랜치)는 upstream LeRobot 0.3.4 위에 ROBOTIS OMX 지원과 WSL2 환경 패치를 얹은 것이다. 전체 소스 대신 upstream 대비 변경분만 둔다.

| 파일 | 내용 |
|---|---|
| `duaro-omx-fork.patch` | upstream `ce3b9f6` → fork HEAD 전체 diff (15 files, +749 / -24) |
| `robots/omx_follower/` | OMX follower 로봇 클래스, 설정, 캘리브레이션 JSON |
| `teleoperators/omx_leader/` | OMX leader 텔레오퍼레이터 클래스, 설정, 캘리브레이션 JSON |

패치에 포함된 DUARO 고유 변경:

- `cameras/opencv/camera_opencv.py`: MJPG fourcc 강제 (YUYV는 usbip 대역폭 초과), async_read 타임아웃 시 직전 프레임 재사용, 기본 타임아웃 200→300 ms
- `teleoperate.py`: `--log_csv` 옵션으로 루프마다 관절값 저장

적용:

```bash
git clone https://github.com/huggingface/lerobot.git && cd lerobot
git checkout ce3b9f6
git apply ../act/lerobot_fork/duaro-omx-fork.patch
pip install -e ".[dynamixel]"
```

설치 절차는 `setup/docs/01_lerobot_setup.md` 참고.
