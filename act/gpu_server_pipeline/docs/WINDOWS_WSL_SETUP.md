# Windows 11 + WSL2 + OMX/camera setup

아래 단계는 **Windows 관리자 PowerShell**, **일반 PowerShell**, **WSL** 중 실행
위치를 구분합니다. USB를 다시 꽂으면 BUSID와 camera PnP path가 바뀔 수 있으므로
항상 현재 값을 다시 확인합니다.

## 1. OpenRB follower를 WSL에 연결

관리자 PowerShell:

```powershell
usbipd list
```

`VID:PID 2f5d:2202` 중 follower의 현재 BUSID를 실제 장치 표식/serial로 확인합니다.
처음 공유할 때만 `bind`하고 WSL에 attach합니다.

```powershell
$followerBusid = 'REPLACE_WITH_CURRENT_BUSID'
usbipd bind --busid $followerBusid
usbipd attach --wsl --distribution Ubuntu-24.04-D --busid $followerBusid
usbipd list
```

카메라는 Windows GStreamer가 소유하므로 WSL에 attach하지 않습니다. WSL에서 follower
stable path를 확인해 `.env`의 `FOLLOWER_PORT`에 그대로 넣습니다.

```bash
ls -l /dev/serial/by-id/
```

`/dev/ttyACM0`처럼 순서가 바뀌는 이름은 사용하지 않습니다.

## 2. 두 카메라 식별

일반 PowerShell:

```powershell
$gstBin = "$env:LOCALAPPDATA\Programs\gstreamer\1.0\msvc_x86_64\bin"
& "$gstBin\gst-device-monitor-1.0.exe" "Video/Source"
```

같은 모델 두 대는 이름으로 구분할 수 없습니다. 출력의 두 `ksvideosrc device-path`
전체를 각각 복사하고, 렌즈를 한 대씩 가려 camera1(손목)과 camera2(외부)를 확인합니다.

```powershell
$cam1ks = '\\\\?\\usb#vid_XXXX&pid_XXXX&mi_00#CURRENT_INSTANCE_1#{6994ad05-93ef-11d0-a3cc-00a0c9223196}\\global'
$cam2ks = '\\\\?\\usb#vid_XXXX&pid_XXXX&mi_00#CURRENT_INSTANCE_2#{6994ad05-93ef-11d0-a3cc-00a0c9223196}\\global'
```

## 3. 노출 설정

GStreamer 폴더에는 `ffmpeg.exe`가 없습니다. 설치된 ffmpeg의 실제 경로를 먼저 찾습니다.

```powershell
$ffmpeg = (Get-Command ffmpeg.exe -ErrorAction Stop).Source
& $ffmpeg -hide_banner -list_devices true -f dshow -i dummy
```

각 Innomaker의 `Alternative name`을 **줄바꿈 없이 한 줄 전체**로 복사합니다. 이때
DirectShow GUID는 `{65e8773d-8f56-11d0-a3b9-00a0c9223196}`이며, 위 GStreamer
`ksvideosrc` GUID와 다릅니다.

```powershell
$cam1dshow = '@device_pnp_\\?\usb#vid_XXXX&pid_XXXX&mi_00#CURRENT_INSTANCE_1#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global'
$cam2dshow = '@device_pnp_\\?\usb#vid_XXXX&pid_XXXX&mi_00#CURRENT_INSTANCE_2#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global'

& $ffmpeg -hide_banner -f dshow -show_video_device_dialog true -i "video=$cam1dshow" -t 1 -f null NUL
& $ffmpeg -hide_banner -f dshow -show_video_device_dialog true -i "video=$cam2dshow" -t 1 -f null NUL
```

각 속성 창에서 다음 값을 사용합니다.

```text
Exposure: -5
Auto Exposure: Off
Low Light Compensation: Disabled
Power Line Frequency: 60 Hz
```

화면이 어두우면 조명 또는 Gain을 조정합니다. 자동 노출/저조도 보정은 실제 FPS를
15–21 Hz로 낮출 수 있습니다.

## 4. Windows에서 WSL로 MJPEG 송신

카메라별로 별도 PowerShell 창을 하나씩 열고, 각 창에서 변수를 다시 선언합니다.
기존 sender와 중복 실행하지 않습니다.

Camera1(손목, UDP 5000):

```powershell
$cam1ks = 'PASTE_CURRENT_KSVIDEOSRC_PATH_ON_ONE_LINE'
$wslIp = ((wsl -d Ubuntu-24.04-D hostname -I) -split '\s+')[0]
$gst = "$env:LOCALAPPDATA\Programs\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"
& $gst -v ksvideosrc device-path="$cam1ks" do-timestamp=true `
  ! "image/jpeg,width=640,height=480,framerate=30/1" `
  ! jpegparse ! rtpjpegpay pt=26 mtu=1400 `
  ! udpsink host=$wslIp port=5000 sync=false async=false
```

Camera2(외부, UDP 5002):

```powershell
$cam2ks = 'PASTE_CURRENT_KSVIDEOSRC_PATH_ON_ONE_LINE'
$wslIp = ((wsl -d Ubuntu-24.04-D hostname -I) -split '\s+')[0]
$gst = "$env:LOCALAPPDATA\Programs\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"
& $gst -v ksvideosrc device-path="$cam2ks" do-timestamp=true `
  ! "image/jpeg,width=640,height=480,framerate=30/1" `
  ! jpegparse ! rtpjpegpay pt=26 mtu=1400 `
  ! udpsink host=$wslIp port=5002 sync=false async=false
```

두 창을 `PLAYING` 상태로 유지합니다. 협상 로그의 `30/1`만 믿지 말고 WSL의
`run_container_preflight.sh`에서 실제 두 ROS topic이 약 30 Hz인지 확인합니다.

## 5. 재연결 체크리스트

전원을 끄기 전에 inference client와 follower bringup을 `Ctrl+C`로 끝냅니다. 다시
연결한 뒤에는 BUSID attach → `/dev/serial/by-id` → 카메라 PnP/노출 → 두 sender →
container/Fast DDS receiver → follower bringup → preflight → 시작 자세 순서로 진행합니다.
