# 설치 안내

이 문서는 Windows 11과 WSL 환경을 기준으로 합니다. Windows에서 실행하는
명령과 WSL에서 실행하는 명령을 구분하여 순서대로 진행하세요.

## Windows PowerShell(관리자 권한)

먼저 다음 프로그램을 Windows에 설치합니다.

- WSL integration을 활성화한 Docker Desktop
- `usbipd-win`
- GStreamer MSVC x86_64
- FFmpeg

설치를 마친 후 관리자 권한 PowerShell에서 현재 USB 장치와 DirectShow 카메라
목록을 확인합니다.

```powershell
usbipd list
ffmpeg -hide_banner -list_devices true -f dshow -i dummy
```

두 OpenRB 장치만 WSL에 attach하세요. 카메라는 Windows의 GStreamer가 직접
사용해야 하므로 Windows 소유 상태로 유지합니다. USB 장치를 뺐다가 다시
연결하면 BUSID가 바뀔 수 있습니다. 아래 명령의 placeholder에는 반드시 현재
`usbipd list`에 표시된 BUSID를 사용하세요.

```powershell
usbipd bind --busid <OPENRB_BUSID>   # first share only
usbipd attach --wsl --busid <FOLLOWER_BUSID>
usbipd attach --wsl --busid <LEADER_BUSID>
```

`usbipd bind`는 해당 OpenRB 장치를 처음 공유할 때만 필요합니다. attach 후에는
`usbipd list`를 다시 실행하여 follower와 leader가 올바르게 WSL에 연결되었는지
확인하세요. 카메라를 WSL에 attach하면 안 됩니다.

각 카메라는 현재 DirectShow 목록에 표시된 alternative name으로 선택합니다.
다음 명령은 카메라 속성 창을 엽니다. 이 창에서 auto exposure와 low-light
compensation을 끌 수 있습니다.

```powershell
$camDshow = '<CURRENT_ALTERNATIVE_NAME>'
ffmpeg -hide_banner -f dshow -show_video_device_dialog true `
  -i "video=$camDshow" -t 1 -f null NUL
```

`<CURRENT_ALTERNATIVE_NAME>`은 위에서 확인한 이름으로 정확히 바꾸세요. 장치
이름에 공백이 포함되어 있다면 공백도 그대로 입력해야 합니다. 카메라 속성 창을
닫고 FFmpeg 명령이 종료된 뒤 다음 단계로 진행합니다.

## WSL

WSL 터미널을 열고 이 저장소의 최상위 디렉터리로 이동한 뒤, 검증된 revision의
두 외부 프로젝트를 설치합니다.

```bash
cd "$HOME/omx-f-zenoh-data-collection"
cp .env.example .env.local
```

먼저 `/dev/serial/by-id/`에서 follower와 leader를 구분하고, 각 basename을
`.env.local`의 `FOLLOWER_BY_ID`와 `LEADER_BY_ID`에 기록합니다. 예를 들어 실제
경로가 `/dev/serial/by-id/usb-ROBOTIS_...-if00`이면 `/` 뒤의 basename 전체를
입력합니다. 실제 serial이 들어간 `.env.local`은 현장 설정 파일이므로 Git에
commit하지 않습니다.

그다음 고정된 upstream을 설치합니다.

```bash
cd "$HOME/omx-f-zenoh-data-collection"
bash scripts/wsl/install_upstreams.sh "$HOME/robot_dependencies"
```

이 helper는 다음 작업을 하나의 검증된 설치 과정으로 수행합니다.

1. `dependencies.lock`에서 Cyclo와 OpenManipulator repository 및 commit을
   읽습니다.
2. 두 upstream을 clone하거나 정확한 commit으로 checkout하고 submodule을
   재귀적으로 초기화합니다.
3. `scripts/wsl/apply_workspace_patches.sh`를 호출하여 `patches/`에 포함된
   배포용 local patch를 적용합니다.
4. 실제 `HEAD`와 전체 local diff가 잠긴 commit 및 기대 diff와 정확히
   일치하는지 검증합니다.

이미 patch가 일부 적용됐거나 upstream에 예상하지 않은 수정이 있거나 exact
diff 검증이 실패하면 helper는 중단해야 합니다. 이 경우 patch를 수동으로
수정하거나 검사를 건너뛰지 말고, 출력된 차이를 보존한 뒤 원인을 확인합니다.
설치 성공 메시지는 단순 clone 완료가 아니라 commit과 patch 검증까지 통과했다는
뜻이어야 합니다.

설치 후 `.env.local`의 경로가 실제 설치 위치와 일치하는지 확인합니다.

```bash
cd "$HOME/omx-f-zenoh-data-collection"
set -a
source .env.local
set +a

test -d "$CYCLO_DIR/.git"
test -d "$OPEN_MANIPULATOR_DIR/.git"
git -C "$CYCLO_DIR" status --short
git -C "$OPEN_MANIPULATOR_DIR" status --short
```

`status --short`에는 installer가 검증한 배포용 patch diff만 나타나야 합니다.
다른 파일이 추가되거나 수정되어 있으면 빌드하지 않습니다.

## 외부 프로젝트 빌드

반드시 pinned checkout과 exact diff 검증을 마친 소스에서 container를
빌드합니다. 아래 명령도 `.env.local`을 읽은 같은 WSL shell에서 실행합니다.

OpenManipulator:

```bash
cd "$OPEN_MANIPULATOR_DIR"
docker compose -f docker/docker-compose.yml \
  build open_manipulator
```

Cyclo:

```bash
cd "$CYCLO_DIR"
ARCH=amd64 docker compose -f docker/docker-compose.yml \
  build cyclo_intelligence
```

빌드가 성공한 뒤에만 container를 시작합니다. 이후 운영 중에는 검증된 container를
불필요하게 다시 만들지 않으며, `docker compose down`으로 기존 환경을 제거하지
않습니다. `--no-build` 기동은 위 최초 빌드를 완료한 뒤에만 사용합니다.

이 시스템에는 ROS 2 Jazzy와 `rmw_zenoh_cpp`가 필요합니다. 서로 통신하는 모든
ROS process에서 다음 값을 동일하게 사용해야 합니다.

```bash
export ROS_DOMAIN_ID=30
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
```

값이 서로 다르면 node, topic, service가 보이지 않거나 통신이 연결되지 않을 수
있습니다.

외부 stack은 host networking/IPC를 사용하며 rosbridge를 외부에 노출합니다.
반드시 신뢰할 수 있는 PC와 네트워크에서만 실행하세요. 다른 host가 접근하지
못하도록 firewall에서 port `7090`과 `7100`을 차단해야 합니다.
