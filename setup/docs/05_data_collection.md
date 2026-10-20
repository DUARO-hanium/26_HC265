# 데이터 수집

## 사전 준비

### 포트 확인
```bash
conda activate lerobot
lerobot-find-port
```
> Leader, Follower 각각 뽑았다 꽂으면서 포트 확인
> 확인한 포트 번호를 명령어의 `--robot.port`, `--teleop.port`에 입력

### WSL2 USB 연결 (매번 필요)
```powershell
# Windows PowerShell 관리자 권한
usbipd attach --wsl --busid <Follower BUSID>
usbipd attach --wsl --busid <Leader BUSID>
usbipd attach --wsl --busid <카메라1 BUSID>
usbipd attach --wsl --busid <카메라2 BUSID>
```

> ⚠️ WSL 재시작 또는 PC 재부팅 시 매번 다시 필요

### 카메라 권한 설정
```bash
sudo chmod 666 /dev/video0
sudo chmod 666 /dev/video1
sudo chmod 666 /dev/video2
sudo chmod 666 /dev/video3
```

### 카메라 인덱스 확인
```bash
ls /dev/video*
```

카메라 하나당 video 장치가 2개씩 잡힘:
```
카메라 1 → /dev/video0 (영상), /dev/video1 (컨트롤)
카메라 2 → /dev/video2 (영상), /dev/video3 (컨트롤)
→ 실제 영상 index: 0, 2
```

> 환경에 따라 다를 수 있으니 ls /dev/video* 로 직접 확인 권장

### HuggingFace 로그인
데이터셋을 HuggingFace Hub에 업로드하여 팀원과 공유하기 위한 방법 중 하나. 로컬에만 저장하려면 `--dataset.push_to_hub=false` 옵션 사용.
```bash
huggingface-cli login --token ${HUGGINGFACE_TOKEN} --add-to-git-credential
HF_USER=$(hf auth whoami | head -n 1)
echo $HF_USER
```

> ⚠️ 텔레오퍼레이션 실행 중이면 반드시 종료 후 진행

---

## 1. 카메라 없이 수집 (joint states + action만)

```bash
conda activate lerobot
lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=omx_follower_arm \
  --teleop.type=omx_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=omx_leader_arm \
  --dataset.repo_id=${HF_USER}/duaro-test \
  --dataset.num_episodes=5 \
  --dataset.single_task="Pick cloth from bag"
```

저장되는 데이터:
```
→ joint states (관절 각도)
→ action (Leader 움직임)
```

---

## 2. 카메라 2개 포함 수집 (권장)

```bash
conda activate lerobot
lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=omx_follower_arm \
  --robot.cameras="{ \
    front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, \
    wrist: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30}}" \
  --teleop.type=omx_leader \
  --teleop.port=/dev/ttyACM1 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --dataset.repo_id=${HF_USER}/duaro-test \
  --dataset.num_episodes=5 \
  --dataset.single_task="Pick cloth from bag"
```

저장되는 데이터:
```
→ joint states (관절 각도)
→ action (Leader 움직임)
→ front 카메라 영상
→ wrist 카메라 영상
```

> ACT 학습에 카메라 영상이 필요하므로 권장

---

## 키보드 단축키

| 키 | 동작 |
|---|---|
| → (오른쪽 화살표) | 에피소드 완료 후 다음으로 |
| ← (왼쪽 화살표) | 현재 에피소드 취소 후 재녹화 |
| ESC | 세션 종료 및 데이터셋 업로드 |

---

## 수집 파라미터

```bash
--dataset.episode_time_s=60   # 에피소드 길이 (초)
--dataset.reset_time_s=60     # 리셋 시간 (초)
--dataset.num_episodes=50     # 총 에피소드 수
--dataset.push_to_hub=false   # HuggingFace 자동 업로드 비활성화
--resume=true                 # 중단된 세션 재개
```

---

## 데이터 저장 위치

```
로컬: ~/.cache/huggingface/lerobot/${HF_USER}/duaro-test
```

HuggingFace 수동 업로드:
```bash
huggingface-cli upload ${HF_USER}/duaro-test \
  ~/.cache/huggingface/lerobot/${HF_USER}/duaro-test \
  --repo-type dataset
```

---

## 참고
- DUARO fork LeRobot record.py: https://github.com/DUARO-hanium/lerobot/blob/feature-omx-devel/src/lerobot/record.py
