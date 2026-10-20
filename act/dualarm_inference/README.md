# dualarm_ACT_inference

ROBOTIS OMX-AI 팔로워 두 대의 **팔별 데이터 수집과 ACT 순차 추론**을 위한 워크스페이스입니다.
왼팔이 봉투를 벌린 뒤 그립을 유지하고, 오른팔이 봉투 속 옷을 꺼냅니다. 두 팔은 각각 별도 데이터셋과 ACT 체크포인트를 사용합니다.

- 환경: **Ubuntu 24.04 LTS · ROS 2 Jazzy · Docker · CPU 추론**
- 공식 OpenMANIPULATOR, Cyclo Intelligence, LeRobot 구현을 재사용합니다.
- 카메라: USB U20 CAM - 720P 3대(top 1대, 손목 각 1대), 1280×720 MJPEG, 목표 30 FPS.

## 설치 및 장치 등록

```bash
git clone https://github.com/DUARO-hanium/dualarm_ACT_inference.git
cd dualarm_ACT_inference
bash scripts/install_host_dependencies.sh
bash scripts/setup.sh
```

공식 소스를 고정 커밋으로 받아 필요한 패치와 CPU 이미지를 준비합니다. 실제 USB 경로는 다음과 같이 등록합니다.

```bash
python3 scripts/devices.py list
python3 scripts/devices.py bind left_follower /dev/serial/by-id/실제_장치_경로
python3 scripts/devices.py bind top /dev/v4l/by-path/실제_장치_경로-video-index0
```

추론에 필요한 역할은 `left_follower`, `right_follower`, `top`, `wrist_left`, `wrist_right`입니다. 수집에는 해당 팔의 `left_leader` 또는 `right_leader`도 등록합니다. 같은 모델 카메라는 고정 USB 포트의 `by-path`를 사용합니다.
설정은 Git에서 제외되는 `config/devices.local.yaml`에 저장됩니다. 카메라 회전 등을 수정하면 `python3 scripts/generate_config.py`를 실행합니다.

## 체크포인트로 CLI 추론

각 ACT 체크포인트의 `pretrained_model` **폴더 전체**를 복사합니다. `config.json`, `model.safetensors`, 저장된 pre/post processor와 정규화 파일이 모두 필요합니다.

```text
checkpoints/left/pretrained_model/
checkpoints/right/pretrained_model/
```

모델은 6차원 state/action(radian)과 `observation.images.top`, `observation.images.wrist`를 사용해야 합니다. 경로·FPS·명령 상한은 [config/inference.yaml](config/inference.yaml)에서 설정합니다.

리더 teleoperation을 종료하고, 다음 명령을 각각 별도 터미널에서 유지합니다. 팔로워 활성화 시 토크가 켜지므로 시작 자세를 준비합니다.

```bash
# 터미널 1: 팔로워 두 대만 활성화; homing 생략
bash scripts/teleop.sh both inference

# 터미널 2: 카메라 세 대
bash scripts/cameras.sh both

# 터미널 3: 왼팔 → 오른팔 수동 전환
bash scripts/infer.sh --side sequence --switch manual
```

`start` + Enter로 시작합니다. 왼팔 성공 시 Enter로 오른팔에 넘기고, 오른팔 성공 시 Enter로 종료합니다. `p`는 일시 정지, `r`은 재개, `q`는 종료이며 모두 Enter로 입력합니다.
한 팔만 실행하려면 `--side left` 또는 `--side right`를 사용합니다. 왼팔의 그립을 유지하려면 전환 중 팔로워 bringup을 계속 실행해야 합니다. CLI 추론 중 Cyclo UI에서 추론을 시작하지 않습니다.

### 마커 없는 자동 전환

ACT와 별도로 top 영상의 성공 상태를 판단하는 LeRobot binary reward classifier가 필요합니다.

```text
checkpoints/left_open_success/pretrained_model/
```

성공 모델은 `observation.images.top` 입력 하나와 `not_open=0`, `open=1` 두 클래스를 사용합니다. 직접 학습하려면 `classifier_images/{train,validation}/{not_open,open}/`에 top RGB 이미지를 분류합니다. 검증 이미지는 다른 시연에서 확보합니다.

```bash
bash scripts/infer.sh --train-success --epochs 20
bash scripts/infer.sh --side sequence --switch auto
```

기본 전환 조건은 왼팔 시작 3초 이후, 성공 확률 ≥0.95와 관절 속도 ≤0.08 rad/s가 1.5초 유지되는 것입니다. 자동 모드에서도 Enter로 전환할 수 있으며 오른팔 종료는 수동입니다. 성공 모델이 없으면 `manual`을 사용합니다.

## 데이터 수집 및 Cyclo UI

```bash
bash scripts/collect.sh left
bash scripts/collect.sh right
# 오른팔 수집 중 준비된 왼팔 자세도 유지하려면: collect.sh right --hold-other
```

[http://localhost:7080](http://localhost:7080)에서 `omx_ai_left` 또는 `omx_ai_right`를 선택해 녹화합니다. 각 팔의 top + wrist 영상과 6축 state/action을 기록합니다. 오른팔은 봉투가 이미 열려 고정된 상태에서 수집하고, Data Tools에서 팔별로 변환·학습합니다.

Cyclo Inference 탭은 `bash scripts/start_ui.sh`로 열고 LeRobot 백엔드와 Robot 모드를 사용합니다. UI 모델 경로는 `/workspace/model/lerobot/left/pretrained_model`이며 오른팔은 `right`로 바꿉니다. UI에서는 Stop 후 프로필과 모델을 바꿔 전환합니다.

## 구성 및 현재 범위

`config/`는 설정, `launch/`는 ROS 실행, `scripts/`는 설치·수집·추론, `patches/`는 공식 소스의 최소 수정입니다. 공식 소스·생성 파일·실행 상태·데이터·체크포인트·개인 USB 설정은 Git에서 제외하고 설치 시 준비합니다.

실물 장치와 학습 가중치로 동작 검증하기 전 상태입니다. 실제 카메라의 720p MJPEG/30 FPS 지원과 동시 전송을 확인해야 하며, CPU 추론의 30 Hz 동작은 보장하지 않습니다.
