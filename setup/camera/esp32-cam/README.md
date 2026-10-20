# ESP32-CAM Wi-Fi 영상 수집

ESP32-CAM(또는 ESP32-S3-CAM)이 찍은 JPEG 프레임을 Wi-Fi(UDP)로 PC에 보내고,
PC에서 실시간으로 띄우면서 mp4로 저장하는 최소 구성입니다.

[CSI-to-image-reconstruction](https://github.com/StrohmayerJ/wificam) 프로젝트에서
카메라 영상 수집에 필요한 부분만 떼어낸 것으로, CSI 수집·모델 학습 코드는 포함하지 않습니다.

```
ESP32-CAM ──(Wi-Fi, UDP :8001, JPEG 1프레임 = 1패킷)──▶ PC server/main.py
                                                          ├─ 실시간 창 표시 (OpenCV)
                                                          └─ server/media/YYYYMMDD_HHMMSS.mp4 저장
      ▲
      └──(USB UART :115200)── tools/SerialConfig (브라우저에서 SSID / IP 설정)
```

## 폴더 구조

```
ESP32-CAM/
├── firmware/
│   ├── esp32_cam/        AI-Thinker ESP32-CAM 펌웨어 (ESP-IDF)
│   │   ├── CMakeLists.txt
│   │   ├── sdkconfig.defaults   PSRAM 활성화 등 기본 설정
│   │   └── main/main.c
│   └── esp32_s3_cam/     ESP32-S3-CAM 펌웨어 (ESP-IDF)
│       ├── CMakeLists.txt
│       ├── sdkconfig            원본에서 생성된 설정 (esp32s3, 2MB flash)
│       ├── sdkconfig.defaults   set-target 시 유지할 핵심 기본값
│       ├── dependencies.lock
│       └── main/main.c
├── server/
│   ├── main.py           UDP 수신 → 화면 표시 + mp4 녹화
│   ├── requirements.txt
│   └── media/            녹화 결과 (git 제외)
└── tools/SerialConfig/   Web Serial 기반 네트워크 설정 도구
    ├── index.html
    ├── script.js
    └── style.css
```

## 1. 준비물

| 구분 | 내용 |
|---|---|
| 보드 | AI-Thinker ESP32-CAM (OV2640, PSRAM 내장) 또는 ESP32-S3-CAM |
| USB-UART | ESP32-CAM은 자체 USB가 없으므로 FTDI/CP2102 같은 USB-TTL 어댑터 필요 (S3도 설정 명령은 UART0 사용; 보드 USB가 UART 브리지인지 확인) |
| PC | Python 3.10 이상, ESP-IDF 5.1 이상 (S3에 포함된 설정/lock은 6.2.0에서 생성; 이 저장소에서 재빌드 검증하지 않음) |
| 네트워크 | 보드와 PC가 같은 2.4 GHz Wi-Fi(WPA2)에 접속 |

## 2. PC 서버 환경 만들기

아래 각 절의 `cd server`, `cd firmware/...` 명령은 프로젝트 루트(`ESP32-CAM`)에서 시작합니다. 서버와 UART 웹 도구는 각각 별도 터미널에서 실행하세요.

```bash
cd server
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

OpenCV 창을 표시할 수 있는 데스크톱 환경이 필요합니다 (`opencv-python-headless` 사용 불가).

## 3. 펌웨어 빌드 / 플래시

ESP-IDF 환경을 활성화한 터미널(Windows는 "ESP-IDF PowerShell", 그 외는 `. $IDF_PATH/export.sh`)에서:

Espressif 공식 설치 절차로 ESP-IDF와 해당 칩 툴체인을 먼저 설치하세요. 첫 빌드는 컴포넌트 다운로드를 위한 인터넷 연결이 필요합니다.

### ESP32-CAM

```bash
cd firmware/esp32_cam
idf.py set-target esp32
idf.py build
idf.py -p COM5 flash monitor      # 포트는 환경에 맞게
```

ESP32-CAM 플래시 시 주의:
- UART 어댑터 TX → U0R(GPIO3), RX → U0T(GPIO1), GND → GND로 연결합니다. UART 신호는 3.3V 레벨을 사용하세요.
- GPIO0 을 GND에 연결한 상태로 전원을 넣어야 다운로드 모드로 들어갑니다.
- 플래시가 끝나면 GPIO0 연결을 떼고 리셋하세요.
- 전원은 5V 핀에 넣는 것이 안정적입니다. 3.3V 핀으로 주면 Wi-Fi 연결 시 브라운아웃이 자주 납니다.

### ESP32-S3-CAM

```bash
cd firmware/esp32_s3_cam
idf.py set-target esp32s3
idf.py build
idf.py -p COM5 flash monitor
```

S3의 `set-target`은 기존 `sdkconfig`를 재생성합니다. 핵심 설정은 `sdkconfig.defaults`에도 포함되어 있습니다 (2MB flash, PSRAM 비활성화, UART0). 보드 사양에 맞게 `idf.py menuconfig`로 확인하세요. S3 다운로드 모드는 보드의 BOOT/RESET 절차를 따릅니다.

첫 빌드 때 `espressif/esp32-camera` 컴포넌트가 자동으로 내려받아져 `managed_components/`에 들어갑니다.

### 카메라 핀 매핑이 다른 보드라면

`main/main.c` 의 `camera_config` 구조체에서 핀 번호를 바꾸면 됩니다.
ESP32 값은 AI-Thinker 기준입니다. S3는 원본 프로젝트의 핀 배치이며 모든 S3-CAM 보드에 공통이 아닙니다. 반드시 보드 회로도와 대조하세요: XCLK=15, SDA=4, SCL=5, D0~D7=11/9/8/10/12/18/17/16, VSYNC=6, HREF=7, PCLK=13, PWDN/RESET=-1.

## 4. 보드 네트워크 설정 (재플래시 없이)

펌웨어는 Wi-Fi SSID/비밀번호와 서버 IP/포트를 NVS에 저장하므로, 코드를 고치지 않고 UART로 바꿀 수 있습니다.

### 방법 A. 브라우저 도구 (권장)

1. 프로젝트 루트에서 `python -m http.server 8080 --bind 127.0.0.1`을 실행하고 Chrome/Edge에서 `http://localhost:8080/tools/SerialConfig/`를 엽니다 (Web Serial API 필요).
2. `idf.py monitor`는 `Ctrl+]`로 종료하여 포트를 해제합니다. UART0에 연결된 USB-UART로 보드를 연결하고 **Connect Device** 를 누른 뒤 COM 포트를 선택합니다 (115200 bps).
3. SSID, Password, Server IP(PC의 IP), Port(기본 `8001`)를 입력하고 **Apply**.
4. **Reboot** 를 누르면 새 설정으로 재시작합니다.

S3의 네이티브 USB Serial/JTAG는 플래시/로그에 쓸 수 있어도 이 펌웨어의 UART0 명령 입력과 다릅니다. UART 브리지가 없는 보드는 외부 USB-UART를 사용하세요 (기본 UART0 TX=GPIO43, RX=GPIO44, 신호 3.3V, 공통 GND).

현재 UART 응답과 브라우저 로그에는 Wi-Fi 비밀번호가 평문으로 포함됩니다. 로그를 공유하지 마세요. 설정 변경 후에는 재시작해야 모든 값이 일관되게 적용됩니다.

PC의 IP 는 Windows 에서 `ipconfig`, macOS/Linux 에서 `ip addr` 또는 `ifconfig` 로 확인합니다.

### 방법 B. 시리얼 모니터에서 직접 입력

115200 bps 로 접속한 뒤 한 줄씩 보냅니다 (줄 끝에 `\n`).

```
SET_SSID:my_wifi
SET_PWD:my_password
SET_IP:192.168.0.10
SET_PORT:8001
GET_CONFIG
RESTART
```

`HELP` 를 입력하면 명령 목록이 나옵니다. `idf.py monitor` 에서도 바로 입력할 수 있습니다.

### 방법 C. 코드에 기본값 박기

`main/main.c` 상단의 `DEFAULT_WIFI_SSID`, `DEFAULT_WIFI_PWD`, `DEFAULT_SERVER_IP`, `DEFAULT_SERVER_PORT` 를 수정하고 다시 플래시합니다.
NVS 에 저장된 값이 있으면 그 값이 우선합니다.

## 5. 실행

1. PC 에서 서버를 먼저 띄웁니다.

   ```bash
   cd server
   python main.py
   ```

   `Image server started on port 8001` 로그가 뜨면 수신 대기 중입니다.

2. 보드에 전원을 넣습니다. Wi-Fi 에 붙으면 바로 프레임을 전송하기 시작합니다.
3. `Real-time Stream` 창에 영상이 뜨고, 1초마다 `Image: NN Hz` 로 수신 프레임 수가 찍힙니다.
4. 종료는 서버 터미널에서 `Ctrl+C`. 녹화 파일은 `server/media/YYYYMMDD_HHMMSS.mp4` 로 저장됩니다.

Windows 방화벽이 Python 의 UDP 8001 수신을 묻는 창을 띄우면 **허용**해야 합니다.

## 6. 동작 상세

### 펌웨어 (`main/main.c`)

- `app_main`: NVS 초기화 → 저장된 설정 로드 → Wi-Fi STA 시작 → UART 콘솔 태스크 시작 → 카메라 초기화 성공 시 전송 태스크 시작. 카메라 실패 시에도 UART 설정 가능
- `udp_image_send_task`: `esp_camera_fb_get()` 으로 JPEG 프레임을 받아 그대로 UDP 한 패킷으로 `sendto`. 끊김 없이 최대 속도로 반복
- `uart_console_task`: UART0 에서 한 줄씩 읽어 `SET_*` / `GET_CONFIG` / `RESTART` 명령 처리, 변경 즉시 NVS 저장
- 카메라 설정: VGA(640×480), JPEG quality 12, 프레임버퍼 2개
  - ESP32-CAM: 프레임버퍼를 PSRAM 에 둠 → `sdkconfig.defaults` 에서 `CONFIG_SPIRAM=y` (부팅 초기화, PSRAM 40MHz)
  - S3-CAM: 프레임버퍼를 내부 DRAM 에 둠 (PSRAM 없는 모듈 기준)

PSRAM 설정명과 속도 제약은 [ESP-IDF 5.1.5 공식 Kconfig 문서](https://docs.espressif.com/projects/esp-idf/en/v5.1.5/esp32/api-reference/kconfig.html#config-spiram-speed)를 기준으로 확인했습니다. ESP32의 PSRAM 80MHz를 선택하려면 플래시도 80MHz로 설정해야 합니다.

### 서버 (`server/main.py`)

- asyncio UDP 엔드포인트가 `0.0.0.0:8001` 에서 패킷을 받습니다. 패킷 하나가 JPEG 한 장입니다.
- 받은 바이트를 두 곳으로 보냅니다.
  - `record_queue` → `record_worker` 스레드: `cv2.imdecode` 후 `VideoWriter`(mp4v, 30 fps) 로 기록. 수신 간격이 들쭉날쭉해도 실제 경과 시간에 맞춰 이전 프레임을 반복 기록하므로 영상 길이가 실제 시간과 맞습니다.
  - `image_queue` → `display_worker` 프로세스: `cv2.imshow` 로 표시. 큐가 차면 표시용 프레임은 버립니다 (녹화에는 영향 없음).
- 설정값은 파일 상단 상수로 조정합니다: `IMAGE_UDP_PORT`, `VIDEO_FPS`.

## 7. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 서버에 `Image: 0 Hz` 만 찍힘 | 보드 시리얼 로그에서 `got ip:` 가 떴는지, `SET_IP` 가 PC IP 와 같은지, 방화벽 UDP 8001 허용 여부 |
| 보드가 `retry to connect to the AP` 반복 | SSID/비밀번호 오타, 5 GHz 전용 SSID 사용, 전원 부족 |
| `Camera init failed` | 핀 매핑 불일치, 카메라 리본 케이블 접촉, ESP32-CAM 은 PSRAM 설정 확인 |
| 화면이 뜨지만 프레임이 깨짐 | IPv4 UDP 페이로드 한도는 65,507바이트이며 이를 넘는 프레임은 전송할 수 없습니다. 네트워크 MTU 를 넘는 JPEG 는 IP 단편화되며, 일부가 유실되면 그 프레임은 디코드 실패로 건너뜁니다. `jpeg_quality` 를 올리거나(값이 클수록 저화질) `frame_size` 를 낮추세요 |
| S3 보드에서 PSRAM 이 있는데 프레임이 느림 | `idf.py menuconfig`에서 보드에 맞는 PSRAM 종류/속도를 활성화하고 `main.c` 의 `fb_location` 을 `CAMERA_FB_IN_PSRAM` 으로 변경 |
| Web Serial 도구에서 포트가 안 보임 | Chrome/Edge 인지, 다른 프로그램(idf.py monitor 등)이 포트를 점유 중인지 확인 |

## 라이선스

Apache License 2.0 (`LICENSE` 참고).
