$ErrorActionPreference = "Stop"

$modelPath = Join-Path (Split-Path $PSScriptRoot -Parent) "yolo26n.pt"
if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "Pretrained YOLO weight not found: $modelPath"
}

$env:CAMERA_1_SOURCE = Join-Path $PSScriptRoot "videos\camera_1.mp4"
$env:CAMERA_1_SIMULATION = "true"
$env:INSPECTION_BACKEND = "yolo"
$env:INSPECTION_MODEL_PATH = $modelPath
$env:INSPECTION_DEFECT_CLASSES = "*"

Write-Host "Detector: pretrained yolo26n.pt (general COCO objects only)"
Write-Warning "This model has not learned garment stains. Do not present its boxes as defect detections."

& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m streamlit run (Join-Path $PSScriptRoot "app.py")
