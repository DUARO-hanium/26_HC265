$ErrorActionPreference = "Stop"

$env:CAMERA_1_SOURCE = Join-Path $PSScriptRoot "videos\camera_1.mp4"
$env:CAMERA_1_SIMULATION = "true"
$env:INSPECTION_BACKEND = "heuristic"

Write-Host "Camera 1: Wi-Fi camera simulation using a recorded video"
Write-Host "SIMULATION is not a real camera or inspection result."
Write-Host "Detector: OpenCV heuristic (training-free reddish-stain candidates)"

& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m streamlit run (Join-Path $PSScriptRoot "app.py")
