# 데이터 계약

이 문서는 녹화를 시작하기 전에 필요한 ROS 2 입력과, 저장된 에피소드를 정상
데이터로 승인하기 위한 최소 조건을 정의한다.

## 필수 입력

| 토픽 | 타입 | 기대 조건 |
|---|---|---|
| `/camera1/image_raw/compressed` | `sensor_msgs/msg/CompressedImage` | 29–31 Hz |
| `/camera2/image_raw/compressed` | `sensor_msgs/msg/CompressedImage` | 29–31 Hz |
| `/joint_states` | `sensor_msgs/msg/JointState` | 약 30 Hz, joint1..5 + gripper |
| `/leader/joint_trajectory` | `trajectory_msgs/msg/JointTrajectory` | 약 30 Hz, 동일한 joint 순서 |
| `/tf` | `tf2_msgs/msg/TFMessage` | 서로 연결된 OMX-F TF 트리 |

영상과 로봇 메시지에는 유효한 acquisition timestamp가 있어야 한다. 모든 ROS 2
프로세스는 Domain 30과 `rmw_zenoh_cpp`를 사용해야 하며, publisher와
subscriber의 QoS도 서로 호환되어야 한다.

토픽이 목록에 보인다는 사실만으로 정상 입력이라고 판단하지 않는다. 녹화를
시작하기 전에 실제 메시지가 계속 들어오는지와 위 표의 주기를 만족하는지
확인한다.

## 완료된 에피소드 판정

정상적으로 완료된 에피소드에는 다음 항목이 있어야 한다.

- 읽을 수 있는 MCAP metadata와 MCAP 데이터
- `episode_info.json`
- 두 카메라의 영상 파일
- 각 영상에 대응하는 timestamp sidecar
- recorder statistics
- 해당 기능을 활성화한 경우 CameraInfo snapshot

Transcode 상태는 `completed` 또는 `not-required`여야 한다.

다음 중 하나라도 해당하면 완료된 에피소드로 승인하지 않는다.

- `.tmp` 파일이 남아 있음
- Transcode 상태가 `failed` 또는 `pending`
- MCAP을 읽을 수 없음
- 로봇 메시지가 누락됨
- 카메라 stream이 누락됨
- Timestamp 사이에 큰 gap이 있음

불완전한 에피소드의 파일명이나 metadata를 임의로 수정해 정상 데이터처럼
보이게 만들지 않는다. 문제 원인을 확인할 수 있도록 실패 데이터와 로그를
분리해 보존한 뒤 다시 녹화한다.

## 공개 및 개인정보 주의

실제 녹화 데이터는 기본적으로 공개하지 않는다. 영상과 metadata에는 사람,
촬영 장소, 작업 지시문, 로봇 및 현장 geometry, 카메라 calibration 정보가
포함될 수 있다. 외부 공유나 업로드 전에는 반드시 데이터 소유권과 개인정보,
현장 보안 정보를 별도로 검토한다.
