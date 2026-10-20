# setup — 하드웨어 설계, 카메라, Teleoperation, Calibration, 환경 구성

로봇을 켜고 데이터를 모으기 전까지 필요한 모든 것. 각 하위 폴더는 원래 별도 저장소였으며 README를 그대로 유지한다.

| 폴더 | 내용 | 원본 저장소 |
|---|---|---|
| `hardware/` | 양팔 Parallel Gripper(좌/우), Z축 리프트 STL/STEP | `3D-Modeling` |
| `camera/esp32-cam/` | Inspection Camera(ESP32-S3-CAM) 펌웨어, UDP 수신 서버, Web Serial 설정 도구 | `ESP32-CAM` |
| `teleoperation/` | Cyclo + rmw_zenoh 기반 Leader-Follower 시연 데이터 수집 운영 절차, 패치, 데이터 계약 | `omx-f-zenoh-data-collection` |
| `calibration/uv_to_world/` | ROS 2 패키지. 체커보드 내부보정, ChArUco hand-eye, 평면 투영으로 (u,v)→`link0` 3D 변환 | `omx-ai-uv-to-world` |
| `calibration/homography/` | 작업대 평면 호모그래피 (u,v)→(x,y), 체커보드 내부 파라미터, `pixel_to_world.py` | `Robot-Action-Pipeline` |
| `calibration/motor/` | Dynamixel 모터 캘리브레이션 래퍼와 이력 | `Robot-Action-Pipeline` |
| `robot_description/omx_f/` | OMX-F follower URDF/xacro, 메시, 커스텀 그리퍼 수정 가이드 | `Robot-Action-Pipeline` |
| `robot_description/omx_l_moveit_config/` | Leader(omx_l) MoveIt2 config | `Robot-Action-Pipeline` |
| `docs/` | LeRobot 설치, 텔레옵, MoveIt/RViz, 카메라 연동, 데이터 수집 가이드, 트러블슈팅, 공통 환경 설정 | `OMX-Setup-Guide`, `Robot-Action-Pipeline/settings.md` |

## 순서

1. `docs/00_environment_settings.md` → WSL2, conda, ROS 2 Jazzy, usbipd
2. `docs/01_lerobot_setup.md` → 팀 fork LeRobot 설치 (`act/lerobot_fork` 패치 포함)
3. `hardware/` 출력물 조립, `calibration/motor/` 그리퍼 교체 후 재캘리
4. `camera/`와 `docs/04_camera_moveit.md` → 카메라 4대 연결 확인
5. `calibration/` → 내부보정, hand-eye 또는 호모그래피
6. `teleoperation/` → 시연 데이터 수집 (데이터 계약 통과분만 채택)

## 카메라 4대

| 역할 | 모델 | 위치 | 연결 |
|---|---|---|---|
| Package | InnoMaker 720P UVC | 패키지 영역 상부 | Windows → RTP/UDP → WSL gscam (`teleoperation/scripts/windows`) |
| Wrist | InnoMaker 720P UVC | 오른팔 손목 | 동일 |
| Vision | Arducam 8MP 1080P | 검수 작업대 상부 | `grasp/vision/run_gscam_b0196.sh` |
| Inspection | ESP32-S3-CAM | 로봇 정면 | Wi-Fi UDP 8001 (`camera/esp32-cam`) |
