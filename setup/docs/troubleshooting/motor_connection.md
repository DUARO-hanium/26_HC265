# Motor Connection Troubleshooting

## Motor ID Missing (XL430, ID 11~13)

### 문제 상황
```
RuntimeError: DynamixelMotorsBus motor check failed
Missing motor IDs: 11, 12, 13
```
```
처음: ID 11만 missing
→ baud rate 57600으로 변경 후: ID 11~16 전부 missing
→ baud rate 1,000,000으로 복구 후: ID 11~13 missing
```

### 과정

**usbipd 설정 (WSL2)**
```powershell
winget install usbipd
usbipd list
usbipd attach --wsl --busid <BUSID>
```

**Windows에서 직접 시도**
```powershell
python -m lerobot.teleoperate `
  --robot.type=omx_follower `
  --robot.port=COM3 `
  --robot.id=omx_follower_arm `
  --teleop.type=omx_leader `
  --teleop.port=COM4 `
  --teleop.id=omx_leader_arm
```
→ 정상 동작 확인 (하드웨어 문제 아님)

**Dynamixel Wizard로 확인**
→ 모터 6개 전부 정상 인식

### Note
- WSL2에서 OMX 연결 시 usbipd 설정이 필요함
- baud rate가 모터 인식에 영향을 줌 (기본값 1,000,000 유지 권장)
- 전원 연결 순서가 모터 인식에 영향을 줄 수 있음

### 해결
USB 및 전원 케이블 전부 뽑고 다시 연결 후 정상 동작

> 권장 순서: 12V → 5V → USB
> 참고: 유사 사례 - https://www.reddit.com/r/robotics/comments/1ktwatv
