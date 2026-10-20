# OMX-F Zenoh 기반 데이터 수집

이 저장소는 ROBOTIS Cyclo 웹 UI를 사용해 OMX-F leader/follower 시연 데이터를
일관된 절차로 수집하기 위한 운영 계층입니다. 처음 설치할 때부터 장치 확인,
실행, 녹화, 종료, 데이터 검증까지 같은 순서로 반복할 수 있도록 구성되어
있습니다.

이 저장소는 Cyclo 소스 코드를 복사하거나 fork하여 포함하지 **않습니다**.
브라우저는 rosbridge를 통해 ROS 2와 통신하고, ROS 2 통신 계층에서는
`rmw_zenoh_cpp`를 사용합니다.

```text
two Windows USB cameras -> RTP/UDP -> gscam
OMX leader/follower -> ROS 2 Jazzy (rmw_zenoh_cpp)
browser -> Cyclo UI -> rosbridge -> Cyclo recorder -> MCAP/video dataset
```

## 가장 먼저 확인할 안전 수칙

teleoperation을 실행하면 follower가 즉시 움직일 수 있습니다. 로봇 주변의 작업
공간을 비우고, 언제든 외부 전원을 끌 수 있는 상태에서 진행하세요. 모터 LED가
점멸하거나 hardware/voltage 오류가 나타나는 경우, 또는 관절에서 비정상적인
열이나 소음이 발생하는 경우에는 즉시 동작을 중단하고 외부 전원을 끄세요.
재부팅을 반복하면서 녹화를 계속하면 안 됩니다.

## 이 저장소가 담당하는 범위

- 설치, 현장별 설정, 사전 점검, 실행 순서, 녹화, 종료 및 데이터셋 검증 절차를
  이 저장소에서 관리합니다.
- Cyclo와 OpenManipulator는 검증된 특정 revision으로 고정된 외부 의존성으로
  유지합니다.
- 카메라 내부 보정, hand-eye 보정, UV-to-world 좌표 변환은 별도의
  `uv_to_world` 저장소에서 관리합니다.
- 실제 로봇 serial, Windows PnP path, token, video, MCAP 및 dataset은 이
  저장소에 commit하지 않습니다.

## 빠른 시작

```bash
git clone \
  https://github.com/DUARO-hanium/omx-f-zenoh-data-collection.git
cd omx-f-zenoh-data-collection
cp .env.example .env.local
```

1. [설치 안내](docs/02_install.md)에 따라 필요한 프로그램과 외부 프로젝트를
   설치합니다.
2. `.env.local`에는 현재 PC와 장치에 해당하는 로컬 값만 입력합니다.
3. 저장소 최상위 디렉터리에서 `bash scripts/wsl/preflight.sh`를 실행합니다.
4. [시스템 실행 및 테스트 episode 녹화](docs/04_bringup.md)에 따라 한 episode를
   시험 녹화합니다.
5. [데이터 계약](docs/05_data_contract.md)을 모두 만족하는 녹화만 정상 데이터로
   채택합니다.
6. 사전 점검이 실패하면 [문제 해결 안내](docs/06_troubleshooting.md)를
   확인합니다.

Cyclo UI의 기본 주소는 <http://localhost:7080>입니다. rosbridge (`7090`)와
supervisor API (`7100`)는 신뢰할 수 없는 네트워크에 노출하지 마세요.

## 검증된 외부 프로젝트 revision

정확한 revision은 [`dependencies.lock`](dependencies.lock)에 기록되어 있습니다.
설치 helper는 다음 순서를 자동으로 수행합니다.

1. Cyclo와 OpenManipulator를 지정된 commit으로 clone 또는 checkout합니다.
2. 각 외부 프로젝트의 submodule을 재귀적으로 초기화합니다.
3. `scripts/wsl/apply_workspace_patches.sh`를 호출해 이 배포에 필요한 local
   patch를 적용합니다.
4. 설치된 upstream commit과 적용된 diff가 이 저장소에 기록된 값과 정확히
   일치하는지 검증합니다.

자동 적용되는 현재 환경용 변경은 다음과 같습니다.

- Cyclo OMX-F 녹화 profile에서
  `/camera2/image_raw/compressed`를 두 번째 카메라로 활성화
- OMX-F follower와 OMX-L leader의 controller update rate를 WSL2 USB/IP
  안정화 값인 `30 Hz`로 변경
- `omx_ai.launch.py`에 `follower_port_name`, `leader_port_name` 인자를 추가해
  현장의 `/dev/serial/by-id/...` 경로를 전달
- trajectory action 결과가 완료된 뒤 다음 초기화 단계로 넘어가도록 수정하고
  동일 goal의 중복 전송을 방지

실제 변경 내용은 [`patches/`](patches/)에서 검토할 수 있습니다.

검증되지 않은 upstream 상태이거나 patch가 일부만 적용된 경우에는 설치를
성공으로 처리하지 않습니다. Patch를 손으로 골라 적용하거나, 고정된 commit을
임의로 최신 `main`으로 바꾸지 마세요. 고정 revision이나 local patch를 변경하는
작업은 일반적인 설치가 아니라 별도의 검토와 재검증이 필요한 업그레이드입니다.

외부 소스를 설치하고 patch 검증을 통과한 다음에만 OpenManipulator와 Cyclo를
빌드합니다. 자세한 명령과 빌드 순서는
[설치 안내](docs/02_install.md)를 따르세요.

저장소를 clone한 뒤 절차를 바로 시작할 수 있지만, 로봇 동작은 의도적으로
one-click 방식으로 만들지 않았습니다. 현장의 장치 역할이 사전 점검을 통과해야
하며, 안전 확인을 마친 사람이 teleoperation을 명시적으로 실행해야 합니다.
실제 leader/follower serial-by-id는 `.env.local`에만 기록하며 Git에 commit하지
않습니다. Teleoperation launch에는 `/dev/ttyACM*`가 아니라 이 by-id 경로를
`follower_port_name`과 `leader_port_name`으로 명시적으로 전달합니다.

UV 보정과 좌표 변환은 별도 저장소인
[`omx-ai-uv-to-world`](https://github.com/DUARO-hanium/omx-ai-uv-to-world)에서
관리합니다.

## 라이선스 및 출처

이 저장소의 운영 문서와 helper script에는 Apache-2.0 라이선스가 적용됩니다.
ROBOTIS Cyclo와 OpenManipulator는 각각 자체 라이선스를 사용하는 별도의 외부
프로젝트이며, 이 저장소는 해당 프로젝트의 소스 코드를 재배포하지 않습니다.
