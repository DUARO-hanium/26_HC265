# Camera Troubleshooting

## WSL2에서 카메라 인식 안 됨 (/dev/video* 없음)

### 문제 상황
```
usbipd attach 했는데도 /dev/video* 없음
ros2 run usb_cam usb_cam_node_exe 실행 시:
→ filesystem error: directory iterator cannot open directory: /sys/class/video4linux/
```

### 원인
```
WSL2 기본 커널에 UVC 드라이버 미포함
→ USB 카메라 꽂아도 /dev/video* 장치 안 생김
```

### 해결 — WSL2 커널 재빌드

**1. 빌드 도구 설치**
```bash
sudo apt update
sudo apt install -y build-essential flex bison libssl-dev libelf-dev \
  bc dwarves libncurses-dev cpio pahole
```

**2. 커널 소스 받기**
```bash
cd ~
git clone --depth 1 --branch linux-msft-wsl-5.15.167.4 \
  https://github.com/microsoft/WSL2-Linux-Kernel.git
cd WSL2-Linux-Kernel
cp Microsoft/config-wsl .config
```

**3. UVC 드라이버 활성화**
```bash
./scripts/config --enable CONFIG_MEDIA_SUPPORT
./scripts/config --enable CONFIG_MEDIA_USB_SUPPORT
./scripts/config --enable CONFIG_MEDIA_CAMERA_SUPPORT
./scripts/config --enable CONFIG_VIDEO_DEV
./scripts/config --enable CONFIG_USB_VIDEO_CLASS
make olddefconfig
```

**4. 활성화 확인**
```bash
grep -E "USB_VIDEO_CLASS|VIDEO_DEV|MEDIA_USB_SUPPORT" .config
```

아래와 같이 나와야 함:
```
CONFIG_VIDEO_DEV=y
CONFIG_MEDIA_USB_SUPPORT=y
CONFIG_USB_VIDEO_CLASS=y
CONFIG_USB_VIDEO_CLASS_INPUT_EVDEV=y
```

**5. 빌드 (30분~1시간 소요)**
```bash
make -j$(nproc)
```

**6. Windows로 커널 복사 (WSL2 터미널)**
```bash
# <YOUR_USERNAME> 부분을 본인 Windows 사용자 이름으로 교체
cp arch/x86/boot/bzImage /mnt/c/Users/<YOUR_USERNAME>/wsl-uvc-kernel
```

**7. .wslconfig 설정 (Windows PowerShell)**
```powershell
# <YOUR_USERNAME> 부분을 본인 Windows 사용자 이름으로 교체
notepad C:\Users\<YOUR_USERNAME>\.wslconfig
```

아래 내용 입력:
```
[wsl2]
kernel=C:\\Users\\<YOUR_USERNAME>\\wsl-uvc-kernel
```

**8. WSL 재시작 (Windows PowerShell)**
```powershell
wsl --shutdown
```

**9. 확인**
```bash
# 커널 변경 확인 (끝에 + 붙어야 함)
uname -r
# 5.15.167.4-microsoft-standard-WSL2+

# 카메라 attach (Windows PowerShell 관리자 권한)
usbipd bind --busid <카메라 BUSID>
usbipd attach --wsl --busid <카메라 BUSID>

# 권한 설정
sudo chmod 666 /dev/video0
sudo chmod 666 /dev/video1

# 장치 확인
ls /dev/video*
# /dev/video0  /dev/video1
```

---

## usb_cam Select timeout 에러 (해결됨)

### 문제 상황
```
Select timeout, exiting...
terminate called after throwing an instance of 'char const*'
```

### 원인
YUYV 포맷이 WSL2 환경에서 불안정하게 캡처됨

### 해결 과정
```
YUYV (기본값)     → Select timeout 에러
mjpeg             → 드라이버가 지원 안 하는 포맷 에러
raw_mjpeg         → timeout은 해결되지만 화면 색이 깨짐 (무지개처럼 지직거림)
mjpeg2rgb         → 정상 작동
```

### 최종 해결 
```bash
ros2 run usb_cam usb_cam_node_exe --ros-args \
  -p pixel_format:=mjpeg2rgb \
  -p image_width:=640 \
  -p image_height:=480
```
