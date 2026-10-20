# LeRobot Setup Guide

## 시스템 환경
- OS: Ubuntu 24.04 (WSL2 포함)
- Python: 3.10

## 주의사항
> ⚠️ `pip install lerobot` 하면 안 됨
> 반드시 ROBOTIS 버전 설치해야 함

---

## 설치 순서

### 1. Miniconda 확인 및 설치

설치 확인:
```bash
conda --version
```
> 버전 나오면 이미 설치된 것 → 2단계로 바로 이동
> Anaconda가 있어도 동일하게 사용 가능

설치 안 돼있으면 (Linux/WSL2):
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash ./Miniconda3-latest-Linux-x86_64.sh
source ~/.bashrc
```
> 참고: https://docs.anaconda.com/miniconda/install/#linux-terminal-install

### 2. 가상환경 생성
```bash
conda create -y -n lerobot python=3.10
```

### 3. 가상환경 활성화
```bash
conda activate lerobot
```
> 터미널 앞에 `(lerobot)` 표시 확인

### 4. FFmpeg 설치
```bash
conda install -c conda-forge ffmpeg=6.1.1 -y
```

> 설치 후 libsvtav1 확인:
> ```bash
> ffmpeg -encoders | grep svt
> ```
> 결과 없으면 아래 중 하나 선택:

**옵션 1 — FFmpeg 7.X 명시 설치**
```bash
conda install ffmpeg=7.1.1 -c conda-forge
```

**옵션 2 — Linux/WSL2에서 직접 빌드 (옵션 1로 해결 안 될 때)**
```bash
which ffmpeg
```
> 직접 빌드 방법은 공식 문서 참고:
> https://trac.ffmpeg.org/wiki/CompilationGuide/Ubuntu

### 5. DUARO 팀 fork LeRobot 클론

> ⚠️ ROBOTIS 원본이 아니라 **팀 fork**를 클론한다. fork에는 팀 패치(카메라 MJPG 강제, teleoperate `--log_csv`, 그리퍼 캘리 JSON)가 이미 반영되어 있어 별도 수정이 필요 없다.

```bash
cd ~
git clone https://github.com/DUARO-hanium/lerobot.git
cd lerobot
```

### 6. 소스 설치
```bash
pip install -e .
```

### 7. Dynamixel SDK 설치
```bash
pip install -e ".[dynamixel]"
```

### 8. 설치 확인
```bash
python -c "import lerobot; print(lerobot.__version__)"
```
> 버전 숫자 나오면 설치 완료

---

## 오류 날 때

### 빌드 에러 날 때
```bash
sudo apt-get install cmake build-essential python-dev pkg-config \
libavformat-dev libavcodec-dev libavdevice-dev \
libavutil-dev libswscale-dev libswresample-dev \
libavfilter-dev pkg-config
```
> 설치 후 `pip install -e .` 다시 실행

---

## 참고 링크
- DUARO 팀 fork LeRobot (셋업은 이걸로): https://github.com/DUARO-hanium/lerobot
- ROBOTIS LeRobot (업스트림 원본): https://github.com/ROBOTIS-GIT/lerobot
- ROBOTIS leRobot Setup Guide: https://ai.robotis.com/omx/setup_guide_lerobot.html
