$ErrorActionPreference = "Stop"

$env:CAMERA_1_SOURCE = "udp://0.0.0.0:8001"
$env:CAMERA_1_SIMULATION = "false"
if (-not $env:UI_REFRESH_MS) { $env:UI_REFRESH_MS = "500" }
if (-not $env:UI_JPEG_QUALITY) { $env:UI_JPEG_QUALITY = "75" }
if (-not $env:INSPECTION_INFER_EVERY) { $env:INSPECTION_INFER_EVERY = "3" }

Write-Host "Listening for ESP32-CAM JPEG frames on UDP port 8001"
Write-Host "Do not run ESP32-CAM/server/main.py at the same time."
Write-Host "Stable display mode: 2 Hz UI, JPEG quality 75, inference every 3 frames"

& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m streamlit run (Join-Path $PSScriptRoot "app.py")
