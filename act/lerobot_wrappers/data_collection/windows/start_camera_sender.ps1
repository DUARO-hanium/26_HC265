# Windows 카메라 → WSL MJPEG/RTP/UDP 송신기
#
# usbipd로 카메라를 WSL에 넘기면 USB/IP의 isochronous 한계로 실측 fps가
# 수 fps까지 떨어진다 (1분 녹화 → 1초 영상 증상). 이 스크립트는 카메라를
# Windows에 둔 채 MJPEG를 RTP/UDP로 WSL에 전송해 그 경로를 우회한다.
# WSL 쪽 수신은 ../camera_bridge.sh (v4l2loopback 가상 카메라로 출력).
#
# 출처: DUARO-hanium/omx-ai-uv-to-world 및 omx-f-zenoh-data-collection의
# scripts/windows/start_camera_sender.ps1 (현장 검증본)을 이 레포로 이식.
# 기본 해상도만 record.sh와 동일한 640x480@30으로 변경.
#
# 사용 예 (카메라 2대 = 창 2개, 각각 실행):
#   front: -Source mf -DeviceIndex <front_index> -WslDistro Ubuntu-24.04 -Port 5000
#   wrist: -Source mf -DeviceIndex <wrist_index> -WslDistro Ubuntu-24.04 -Port 5001
# 장치 index 확인: gst-device-monitor-1.0.exe "Video/Source"
# 주의: 카메라를 usbipd attach 하지 않은 상태여야 한다 (Windows가 사용).

param(
  [Parameter(Mandatory=$true)]
  [ValidateSet("mf","ks")]
  [string]$Source,
  [string]$DevicePath,
  [int]$DeviceIndex = -1,
  [Parameter(Mandatory=$true)]
  [string]$WslDistro,
  [ValidateRange(1, 2147483647)][int]$Width = 640,
  [ValidateRange(1, 2147483647)][int]$Height = 480,
  [ValidateRange(1, 2147483647)][int]$Fps = 30,
  [Parameter(Mandatory=$true)]
  [ValidateRange(1, 65535)][int]$Port
)

$ErrorActionPreference = "Stop"
if ($Source -eq "mf") {
  if ($DeviceIndex -lt 0) {
    throw "-DeviceIndex must be a non-negative integer when -Source mf is used"
  }
  if ($DevicePath) {
    throw "-DevicePath and -DeviceIndex are mutually exclusive; use only -DeviceIndex with -Source mf"
  }
} else {
  if (!$DevicePath) {
    throw "-DevicePath is required when -Source ks is used"
  }
  if ($DeviceIndex -ge 0) {
    throw "-DevicePath and -DeviceIndex are mutually exclusive; use only -DevicePath with -Source ks"
  }
}

$gstDir = "$env:LOCALAPPDATA\Programs\gstreamer\1.0\msvc_x86_64\bin"
$gst = "$gstDir\gst-launch-1.0.exe"
if (!(Test-Path $gst)) { throw "gst-launch-1.0.exe not found: $gst" }

$wslIp = ((wsl -d $WslDistro hostname -I) -split '\s+')[0]
if (!$wslIp) { throw "WSL IP not found for $WslDistro" }
$caps = "image/jpeg,width=$Width,height=$Height,framerate=$Fps/1"

Write-Host "source=$Source ${Width}x${Height}@${Fps} -> ${wslIp}:$Port"
if ($Source -eq "mf") {
  # 주의: MF MJPEG 경로에 jpegparse를 넣으면 stream error 발생 이력 → 넣지 않는다
  Write-Host "device-index=$DeviceIndex"
  & $gst -v mfvideosrc device-index=$DeviceIndex do-timestamp=true `
    ! $caps ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream `
    ! rtpjpegpay pt=26 mtu=1400 `
    ! udpsink host="$wslIp" port=$Port sync=false async=false
} else {
  # gst-launch joins its native argv back into a pipeline string and parses
  # that string once more. Escape Windows separators for the second parse.
  $gstDevicePath = $DevicePath.Replace('\', '\\')
  $devicePathArg = "device-path=$gstDevicePath"
  Write-Host "device-path=$DevicePath"
  & $gst -v ksvideosrc $devicePathArg do-timestamp=true enable-quirks=true `
    ! $caps ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream `
    ! jpegparse ! rtpjpegpay pt=26 mtu=1400 `
    ! udpsink host="$wslIp" port=$Port sync=false async=false
}
