# 문제 해결

문제가 발생하면 같은 명령을 반복 실행하기 전에 기존 프로세스가 이미 실행
중인지 확인한다. Zenoh daemon, gscam receiver, 카메라 sender를 중복 실행하면
토픽 검색과 주기가 불안정해질 수 있다.

## UI 7080에 접속할 수 없음

Cyclo container가 실행 중인지 확인하고 UI service 상태를 점검한다. UI가
실행되는 PC에서 <http://localhost:7080>으로 접속했는지도 확인한다.

UI뿐 아니라 supervisor API와 rosbridge도 필요하다. 포트 설정을 변경했다면
`.env.local`과 Cyclo 설정이 같은 값을 사용하는지 확인한다.

## UI는 열리지만 토픽이 보이지 않음

다음 항목을 순서대로 확인한다.

- rosbridge가 7090에서 실행 중인지
- Zenoh daemon이 정확히 하나만 실행 중인지
- 모든 ROS 2 프로세스가 Domain 30을 사용하는지
- 모든 ROS 2 프로세스가 `rmw_zenoh_cpp`를 사용하는지
- publisher와 recorder의 QoS가 호환되는지

설정을 수정한 뒤 UI의 토픽 목록을 새로고침한다. 토픽이 없다는 이유만으로
Zenoh daemon이나 recorder를 추가로 실행하지 않는다.

## 토픽 검색이 중복되거나 주기가 불안정함

중복 실행된 zenoh, gscam 또는 sender 프로세스가 있는지 확인한다. 각 구성요소는
필요한 개수만 남기고 중복 프로세스를 종료한다.

- Zenoh daemon: 1개
- gscam receiver: 카메라별 1개
- Windows camera sender: 카메라별 1개

기존 프로세스 상태를 확인하지 않은 채 같은 launch나 sender를 다시 실행하지
않는다.

## OpenRB 장치를 찾을 수 없음

Windows 관리자 PowerShell에서 `usbipd list`를 다시 실행한다. USB를 다시
연결하면 BUSID가 바뀔 수 있으므로 현재 BUSID로 OpenRB를 WSL에 attach한다.

WSL에서는 `/dev/serial/by-id`를 확인한다. `ttyACM0`과 같은 번호는 재연결 후
바뀔 수 있으므로 장치 선택 기준으로 사용하지 않는다. 사용자가 `dialout`
그룹에 속해 있고 해당 장치를 읽고 쓸 권한이 있는지도 확인한다.

카메라는 Windows가 사용하므로 WSL에 attach하지 않는다.

## 카메라가 busy 상태이거나 주기가 느림

같은 카메라를 사용하는 Windows Camera 앱, 화상회의 앱, FFmpeg 속성 창,
중복 sender를 먼저 종료한다. `gst-device-monitor-1.0`으로 현재 PnP path를
다시 확인한다. USB 재연결 후에는 이전 path를 그대로 사용하지 않는다.

카메라 속성 창에서 auto exposure와 low-light compensation을 끄고 노출을 다시
확인한다. GStreamer pipeline이 `PLAYING`이라고 표시되는 것만으로 실제 주기가
정상이라는 뜻은 아니다. 설정 후 ROS 토픽 주기를 다시 측정하며, 카메라 입력은
29–31 Hz를 만족해야 한다.

## 녹화 결과가 불완전함

실패한 에피소드는 원인 분석 자료로 보존한다. `.tmp` 파일의 이름을 바꾸거나
metadata를 편집해 완료된 데이터처럼 만들지 않는다.

다음을 확인한다.

- MCAP과 metadata를 읽을 수 있는지
- 두 카메라 영상과 timestamp sidecar가 모두 있는지
- 로봇 토픽 메시지가 저장되었는지
- Transcode 상태가 `completed` 또는 `not-required`인지
- 큰 timestamp gap이 없는지

불완전 판정 기준은 [`05_data_contract.md`](05_data_contract.md)를 따른다.

## 디스크 공간이 부족함

녹화를 시작하기 전에 중단하고 충분한 여유 공간을 확보한다. 녹화 중 디스크가
가득 차면 MCAP, 영상, metadata가 함께 손상될 수 있다.

Dataset과 영상은 Git 저장소 밖에 보관해야 한다. 실제 MCAP, MP4, timestamp
sidecar 또는 녹화 metadata를 Git에 commit하지 않는다.

## 모터 LED 점멸 또는 hardware error

로봇 동작과 녹화를 즉시 중단하고 follower 외부 전원을 끈다. 팔과 장착물이
떨어지지 않도록 안전하게 지지한 뒤 hardware와 오류 로그를 확인한다.

LED 점멸, voltage/overheating/overload 오류, 비정상적인 열이나 소음이 발생한
상태에서 반복적으로 reboot하거나 teleoperation과 녹화를 계속하지 않는다.
원인을 확인할 수 없거나 같은 오류가 재발하면 장비 점검 또는 공식 서비스를
요청한다.
