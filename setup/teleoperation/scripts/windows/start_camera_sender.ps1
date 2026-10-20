param(
  [Parameter(Mandatory=$true)][string]$WslDistro,
  [Parameter(Mandatory=$true)][string]$DevicePath,
  [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$Port,
  [ValidateRange(1,4096)][int]$Width = 640,
  [ValidateRange(1,2160)][int]$Height = 480,
  [ValidateRange(1,120)][int]$Fps = 30
)

$ErrorActionPreference = "Stop"
$gst = "$env:LOCALAPPDATA\Programs\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"
if (!(Test-Path $gst)) { throw "GStreamer not found: $gst" }
$wslIp = ((wsl -d $WslDistro hostname -I) -split '\s+')[0]
if (!$wslIp) { throw "WSL IP not found for $WslDistro" }

$escapedPath = $DevicePath.Replace('\', '\\')
$pathArgument = "device-path=$escapedPath"
$caps = "image/jpeg,width=$Width,height=$Height,framerate=$Fps/1"

Write-Host "${Width}x${Height}@${Fps} -> ${wslIp}:$Port"
& $gst -v ksvideosrc $pathArgument do-timestamp=true enable-quirks=true `
  ! $caps ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream `
  ! jpegparse ! rtpjpegpay pt=26 mtu=1400 `
  ! udpsink host="$wslIp" port=$Port sync=false async=false
exit $LASTEXITCODE
