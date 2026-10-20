# Teleoperation Setup

## 순서 요약
```
1. WSL2 USB 연결 (Windows PowerShell)
2. USB 포트 찾기
3. 텔레오퍼레이션 실행
4. (선택) udev rules 설정
```

---

## 1. WSL2 USB 연결

```powershell
# Windows PowerShell 관리자 권한
usbipd list
# → OMX Follower, OMX Leader BUSID 확인

usbipd attach --wsl --busid <Follower BUSID>
usbipd attach --wsl --busid <Leader BUSID>
```

> 카메라도 같이 쓸 경우 카메라 BUSID도 추가로 attach 필요(04_camera_moveit.md 참고)

---

## 2. USB 포트 찾기

Leader, Follower 각각 뽑았다 꽂으면서 포트 확인:
```bash
conda activate lerobot
lerobot-find-port
```

출력 예시:
```
(lerobot) username@username:~/lerobot$ lerobot-find-port
Finding all available ports for the MotorsBus.
Ports before disconnecting: ['/dev/ttyACM1', '/dev/ttyACM0', ...]
Remove the USB cable from your MotorsBus and press Enter when done.
```

Leader 또는 Follower USB 뽑고 Enter 누르면:
```
The port of this MotorsBus is '/dev/ttyACM1'
Reconnect the USB cable.
```

반대쪽도 동일하게 반복해서 두 포트 모두 확인.

이 튜토리얼에서는:
- Follower 포트 → /dev/ttyACM0
- Leader 포트 → /dev/ttyACM1

---

## 3. 텔레오퍼레이션 실행

### 기본 실행
```bash
python -m lerobot.teleoperate \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=omx_follower_arm \
  --teleop.type=omx_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=omx_leader_arm
```

> ⚠️ `--robot.id/--teleop.id` 값은 캘리브레이션 등 설정이 저장되므로
> 텔레오퍼레이션, 녹화, 실행 전체에서 동일하게 유지할 것

### 카메라 포함
```bash
python -m lerobot.teleoperate \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=omx_follower_arm \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}}" \
  --teleop.type=omx_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=omx_leader_arm \
  --display_data=true
```

---

## 4. udev rules 설정 (선택사항)

> ⚠️ WSL2 환경에서는 적용 안 될 수 있음 (네이티브 Ubuntu 권장)
> 로봇을 자주 뽑았다 꽂는 경우에만 설정 권장
>
> 출처: https://huggingface.co/docs/lerobot/omx

### 시리얼 번호 확인
```bash
ls -l /dev/serial/by-id/
```

출력 예시:
```
usb-ROBOTIS_OpenRB-150_228BDD7B503059384C2E3120FF0A2B19-if00 -> ../../ttyACM0
usb-ROBOTIS_OpenRB-150_67E1ED68503059384C2E3120FF092234-if00 -> ../../ttyACM1
```
> `usb-ROBOTIS_OpenRB-150_` 뒤부터 `-if00` 앞까지가 시리얼 번호

### udev rule 파일 생성
```bash
sudo nano /etc/udev/rules.d/99-omx.rules
```

아래 내용 붙여넣기 (시리얼 번호는 본인 것으로 교체):
```
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{serial}=="시리얼번호_follower", SYMLINK+="omx_follower"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{serial}=="시리얼번호_leader", SYMLINK+="omx_leader"
```

### 적용
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 확인
```bash
ls -l /dev/omx_follower /dev/omx_leader
```

출력 예시:
```
/dev/omx_follower -> ttyACM0
/dev/omx_leader   -> ttyACM1
```

> 설정 후 로봇 한 번 뽑았다 다시 꽂기
> 이후 명령어에서 `/dev/ttyACM0` 대신 `/dev/omx_follower` 사용 가능

---

## 주의사항
- 명령어 정확하게 입력할 것
- Leader/Follower 포트 헷갈리지 않게 주의
- 로봇 뽑았다 꽂으면 `lerobot-find-port` 다시 실행해서 포트 확인

---

## 참고 링크
- ROBOTIS 튜토리얼: https://ai.robotis.com/omx/lerobot_imitation_learning_omx
