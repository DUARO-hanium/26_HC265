# DUARO 실시간 검수 대시보드

이 버전은 설정된 카메라에서 프레임을 계속 받고, 선택한 검출기의 결과를 즉시 화면과 검수 이력에 반영합니다. 기본 검출기는 학습 없이 현재 회색 의류의 붉은 오염 후보를 찾는 OpenCV 규칙 기반 방식이며, 학습 데이터가 준비되면 설정만 바꿔 YOLO로 교체할 수 있습니다.

## 동작 구조

1. 백그라운드 작업자가 DUARO ESP32-CAM의 UDP 8001 JPEG 프레임을 직접 받습니다.
2. 지연 누적을 피하기 위해 최신 프레임만 보관합니다.
3. 한 검출기를 공유해 프레임을 분석하고, 후보 박스와 점수를 그립니다.
4. UI는 실제 연결 여부, FPS, 추론 시간, 프레임 지연, 검출 개수를 약 0.2초 간격으로 표시합니다.
5. `검수 시작`부터 `판정 확정` 사이에 한 번이라도 검출된 결함의 최고 신뢰도를 상품 이력으로 저장합니다.

## 설치와 실행

```powershell
cd inspection_dashboard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:CAMERA_1_SOURCE = "udp://0.0.0.0:8001"
$env:INSPECTION_BACKEND = "heuristic"
streamlit run app.py
```

`DUARO-hanium/ESP32-CAM` 펌웨어는 RTSP가 아니라 JPEG 프레임을 MTU 이하의 작은 UDP 조각으로 나눠 PC에 전송합니다. 대시보드는 프레임 ID와 조각 번호를 이용해 JPEG를 다시 조립하며, 예전의 JPEG 한 장/UDP 한 패킷 형식도 받을 수 있습니다. 별도의 `ESP32-CAM/server/main.py`를 함께 실행하지 마세요. 대시보드가 UDP 8001 포트를 직접 사용합니다.

```powershell
$env:CAMERA_1_SOURCE = "udp://0.0.0.0:8001"
```

지원 설정은 `.env.example`에 정리되어 있습니다. `.env` 파일을 자동으로 읽지는 않으므로 실행 셸, 서비스 설정 또는 Docker Compose의 환경 변수로 주입하세요.

## 장비 도착 전 Wi-Fi 카메라 시뮬레이션

기존 녹화 영상을 Wi-Fi 카메라 프레임처럼 반복 입력하여 캡처와 UI 갱신 경로를 미리 확인할 수 있습니다. 화면과 상태에 `SIMULATION`이 명시되므로 실제 검수와 혼동되지 않습니다.

```powershell
.\run_wifi_simulation.ps1
```

실제 카메라는 `run_esp32_camera.ps1`로 실행합니다. ESP32에는 같은 2.4GHz Wi-Fi의 SSID/비밀번호, 이 PC의 Wi-Fi IPv4 주소, 포트 8001을 UART 설정 도구로 저장해야 합니다.

```powershell
.\run_esp32_camera.ps1
```

실제 카메라 실행은 안정성을 우선해 브라우저 화면을 500ms마다 갱신하고, 표시용 JPEG 품질을 75로 낮추며, 검출은 3번째 수신 프레임마다 수행합니다. `st.image`의 빠른 임시 URL 교체 대신 자체 포함 JPEG를 사용하므로 수신 수치는 정상인데 화면만 깨지는 현상을 방지합니다. 더 느리게 표시하려면 실행 전에 `$env:UI_REFRESH_MS="1000"`을 지정하세요.

ESP32-S3 펌웨어의 `STREAM_FRAME_DELAY_MS`도 180ms로 조정되어 있습니다. 이 네트워크 송신률 제한은 펌웨어를 다시 빌드하고 플래시해야 적용되며, 대시보드 수정만 사용해도 브라우저 표시 안정화는 적용됩니다.

일반 사전학습 YOLO와의 인터페이스 연결을 확인하려면 다음을 실행합니다. 저장소의 `../yolo26n.pt`를 자동으로 사용하고 모든 COCO 클래스를 표시하지만, 이 박스는 의류 결함 결과가 아닙니다.

```powershell
.\run_yolo_pretrained_simulation.ps1
```

## 카메라 없이 녹화 영상 검수

저장된 영상도 모델 파일 없이 규칙 기반 검출기로 검사할 수 있습니다. 결과는 bbox가 표시된 MP4와 판정 근거를 담은 JSON으로 저장됩니다.

```powershell
.\.venv\Scripts\python.exe .\inspect_video.py `
  "D:\Users\23011\Downloads\KakaoTalk_20260908_004817477.mp4" `
  --start-seconds 235 --end-seconds 310 `
  --output ".\outputs\return_0001.mp4"
```

기본 추론은 전체 프레임과 겹치는 2x2 crop을 함께 사용합니다. 작은 얼룩이 모델 입력에서 너무 작아지는 현상을 완화하고, 겹쳐 검출된 박스는 class-aware NMS로 합칩니다. 비교 실험 시 `--full-frame-only`로 crop을 끌 수 있습니다.

대시보드에 `ESP32-CAM 프레임 대기 중`이 표시되면 수신 준비가 된 것입니다. 보드가 프레임을 보내기 시작하면 자동으로 영상과 FPS가 표시됩니다.

## 중요한 모델 조건

### 지금 바로 사용하는 규칙 기반 검출기

`INSPECTION_BACKEND=heuristic`은 모델 파일 없이 HSV/Lab 색상 차이, 형태학적 노이즈 제거, 연결요소 면적 필터로 `stain_candidate`를 생성합니다. 표시되는 값은 AI confidence가 아니라 규칙 기반 `score`입니다. 현재 회색 의류와 붉은 오염처럼 대비가 뚜렷한 촬영 조건을 대상으로 하며, 다른 색상·무늬·조명에서는 임계값 재조정이 필요합니다.

현재 오검출 억제 설정은 원시 R값이 아니라 `R-(G+B)/2`와 정규화된 R 비율을 함께 검사하고, 후보 주변에 회색 원단과 유사한 저채도 픽셀이 충분한지 확인합니다. 또한 같은 위치에서 3번 연속 확인된 가장 강한 후보 1개만 화면과 판정에 반영합니다.

녹화 영상에 준비 과정이나 배경 장면이 포함돼 있으면 `--start-seconds`와 `--end-seconds`로 실제 검수 구간만 분석해야 합니다. 실시간 대시보드에서는 옷이 검사 위치에 놓인 뒤 `검수 시작`을 눌러 같은 역할을 합니다.

### 데이터가 준비된 뒤 YOLO로 전환

```powershell
$env:INSPECTION_BACKEND = "yolo"
$env:INSPECTION_MODEL_PATH = "C:\models\garment_defect_best.pt"
$env:INSPECTION_DEFECT_CLASSES = "stain,discoloration,damage,tear,hole"
streamlit run app.py
```

저장소 루트의 `yolo26n.pt`는 일반 객체 검출 모델이므로 의류 얼룩·찢김 검수 모델로 사용할 수 없습니다. 실제 검수를 위해서는 `stain`, `discoloration`, `damage`, `tear`, `hole` 같은 결함 클래스로 학습한 가중치가 필요합니다. 모델의 클래스명이 다르면 `INSPECTION_DEFECT_CLASSES`를 맞춰야 합니다. `*`로 설정하면 모델이 검출한 모든 클래스를 불량으로 취급합니다.

모델 또는 카메라가 준비되지 않았을 때 UI는 연결됨으로 가장하지 않고 구체적인 오류를 표시합니다. 로봇 상태는 아직 ROS 2 상태 토픽과 연결하지 않았기 때문에 `미연동`으로 표시합니다.

현재 MVP가 실제로 판정하는 항목은 **오염·변색·찢어짐·구멍 등 상품 상태**입니다. 사이즈 오배송은 라벨 OCR/바코드와 주문 SKU 비교, 색상 오배송은 조명 보정된 색상 특징과 주문 SKU 비교가 필요하므로 결함 YOLO에 섞지 않고 다음 모듈로 분리합니다.

## ROS 2 카메라를 사용하는 경우

현재 구현의 입력 경계는 OpenCV `VideoCapture`입니다. 기존 `/camera1/image_raw/compressed`, `/camera2/image_raw/compressed`를 쓰려면 다음 중 하나를 선택할 수 있습니다.

- gscam/RTSP 게이트웨이로 스트림 URL을 제공해 그대로 연결
- 별도 ROS 2 수집 프로세스가 JPEG/MJPEG 엔드포인트를 제공
- `CameraWorker`에 `rclpy` 구독 어댑터를 추가

운영 환경에서는 UI와 GPU 추론 프로세스를 분리하고 ROS 2 토픽 또는 메시지 큐로 `frame_id`, `timestamp`, `detections`, `verdict`를 전달하는 구성이 안정적입니다. 이 대시보드는 단일 PC에서 바로 검증할 수 있는 MVP입니다.
