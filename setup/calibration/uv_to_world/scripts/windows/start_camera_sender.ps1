param(
  [Parameter(Mandatory=$true)]
  [ValidateSet("mf","ks")]
  [string]$Source,
  [string]$DevicePath,
  [int]$DeviceIndex = -1,
  [Parameter(Mandatory=$true)]
  [string]$WslDistro,
  [ValidateRange(1, 2147483647)][int]$Width = 1280,
  [ValidateRange(1, 2147483647)][int]$Height = 720,
  [ValidateRange(1, 2147483647)][int]$Fps = 30,
  [ValidateRange(1, 65535)][int]$Port = 5000
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
