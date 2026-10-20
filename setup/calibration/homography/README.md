# calibration/camera — 픽셀 (u,v) ↔ world 좌표 변환

**목적:** RGB 카메라가 검출한 픽셀 좌표를 로봇이 이동 가능한 world 좌표(x, y)로 변환 → 없으면 비전이 찾은 지점으로 로봇을 보낼 수 없음, rule-base 경로에서 vision을 motion으로 연결할 때 사용

**참고:** RGB 단안이라 depth 없음 → 타겟이 고정된 평면(작업대·봉투 거치대) 위에 있다고 가정하고 Homography H (3×3) 를 사전에 만듬

**⚠️ 단계별 사용 환경이 다름** — 캘리브레이션은 두 환경을 번갈아 사용 (한 터미널에서 섞지 말 것):

| 단계 | 터미널 환경 | 성격 |
|---|---|---|
| 마커 검출·H 생성·변환 검증 (`aruco_homography.py` 등 이 폴더 스크립트) | `conda activate lerobot` (Python 3.10) | 순수 OpenCV 프로그램 — ROS 무관 |
| TABLE_Z 측정·좌표축 확인 (RViz·bringup·`tf2_echo`) | `rosenv` (시스템 3.12, **conda 끔**) | ROS2 도구 |

## 파일 구성

**스크립트:**

| 파일 | 역할 |
|---|---|
| `aruco_homography.py` | ArUco 마커 4장 검출 → H 계산 → JSON 저장 | 
| `checkerboard_intrinsics.py` | 체커보드로 K(내부파라미터)·dist(왜곡) 측정 | 
| `robot_touch_homography.py` | 로봇 EE 터치 방식 → H 계산 (마커 대안) | 

**JSON — 입력 (직접 작성):**

| 파일 | 내용 |
|---|---|
| `marker_world_table.json` | 작업대 마커 4장의 world 좌표 실측값 |
| `marker_world_bag.json` | 봉투 거치대 마커용 |

**JSON — 출력 (스크립트 실행 시 자동 생성, 직접 만들지 말 것):**

| 파일 | 생성 명령 | 내용 |
|---|---|---|
| `H_table.json` | `aruco_homography.py --output H_table.json` | 작업대 평면 픽셀 → world 변환 행렬 (옷 grasp point용) |
| `H_bag.json` | `aruco_homography.py --output H_bag.json` | 봉투 거치대 평면용 — 개구부 접근을 모방학습으로 한다면 필요 X |
| `intrinsics.json` | `checkerboard_intrinsics.py` | 카메라 내부파라미터 K, 왜곡계수 dist |



## 두 가지 대응점 획득 방법

|  | ArUco 마커 | 로봇 터치 |
|---|---|---|
| 대응점 | 마커 4장 자동 검출 | EE 터치 + FK |
| world 좌표 출처 | 줄자 1회 측정 | FK (자 불필요) |
| 추가 필요 | 프린터 (마커 출력) | 그리퍼 TCP 오프셋 |
| 재캘리 | 스크립트 재실행만 | 터치 반복 |

<br/>
<br/>

# 준비 사항

## 1. ArUco 마커 인쇄

- **사전: `DICT_4X4_50`** — 스크립트에 하드코딩돼 있으므로 반드시 이 사전으로 출력
- 생성 사이트: https://chev.me/arucogen/ → Dictionary `4x4 (50)`, Marker ID `0, 1, 2, 3`, size `50mm` 로 4장
- **한 변 5cm**, 여백 포함 A4 인쇄 (축소/맞춤 인쇄 금지 — 실측 크기가 달라짐)
- 인쇄 후 자로 실제 5cm인지 확인

## 2. 마커 부착

- 작업대 **바깥 4모서리** 근처, 로봇 팔·옷에 **가려지지 않는 위치**
- 반드시 **평평하게** (들뜨거나 휘면 오차 급증) — 테이프로 네 귀퉁이 고정
- **4장이 일직선이 되지 않게** 사각형 형태로 배치 (일직선이면 H 계산 실패)
- 카메라 화면에서 4장이 **모두 동시에 보이는지** 확인

## 3. world 좌표 실측

- 기준: **로봇 베이스 원점** — 카메라 위치 아님 (카메라가 어디 있든 그 효과는 H가 흡수함). H의 출력이 "로봇이 이동할 좌표"이므로 **로봇 모션(MoveIt2/IK)이 쓰는 좌표계와 동일해야** 함
  - 원점 실물 위치 (omx_f.urdf 확인): `world` = `link0`(베이스) 원점. **주의 — shoulder_pan(joint1) 회전축은 원점과 정확히 일치하지 않음**: 축이 원점 기준 x −11.25mm, z +34mm에 있음 (`joint1 origin xyz="-0.01125 0 0.034"`). 줄자 기준점을 pan 축으로 잡으면 x에 +0.01125 보정 필요
  - **그래서 (x, y) 기준점도 실물에서 눈대중으로 짚지 말고, EE 터치 + `tf2_echo`로 잡는 게 가장 정확** — EE를 마커 중심에 대고 tf2_echo의 (x, y)를 읽으면 원점 위치 고민 자체가 사라짐 (TABLE_Z 측정과 같은 요령, TCP의 수평 오프셋만 주의)
  - 축 방향 확인법: RViz TF 축 표시(빨강=x, 초록=y) 또는 EE를 임의 위치에 두고 `tf2_echo world end_effector_link` 값 vs 줄자 실측 비교. ROS 관례상 보통 x=전방, y=좌측(+), z=위

  **RViz에서 축 보는 법** (RViz 실행·사전 셋팅은 맨 아래 "참고 — RViz로 좌표축 확인" 섹션):
  1. RViz 창 왼쪽 **Displays** 패널에서 **TF** 항목 체크 (없으면 하단 Add → TF)
  2. TF 펼쳐서 Frames 중 `base_link`(또는 `world`)만 체크하면 화면이 깔끔함
  3. 로봇 베이스에 표시되는 화살표: **빨강=x축, 초록=y축** — 이 방향대로 줄자 측정
  4. 헷갈리면 검증: EE를 임의 지점에 두고 터미널에서
     ```bash
     ros2 run tf2_ros tf2_echo world end_effector_link
     ```
     출력된 (x, y)와 줄자 실측값의 부호·크기를 비교
- 각 마커의 **중심점**까지 (x, y) 측정 — **직선거리가 아니라 축별 성분** (x축 방향 얼마, y축 방향 얼마 따로), **단위 m** (예: 30cm → `0.30`)
- 실측 정밀도: **±2~3mm**(mm 단위까지 읽기)면 충분 — 최종 변환 정확도 목표가 ±1cm(옷 파지엔 여유 있음)이므로
- 측정값으로 `marker_world_table.json` 파일을 직접 작성 (형식만 아래 참조 — **값은 반드시 실측값**):

```jsonc
// marker_world_table.json — "마커ID": [x, y] (m 단위, 로봇 베이스 기준 실측값)
{
  "0": [<x>, <y>],
  "1": [<x>, <y>],
  "2": [<x>, <y>],
  "3": [<x>, <y>]
}
```

### TABLE_Z 측정 (로봇 터치 + FK)

```bash
# 터미널 0: Zenoh 라우터 (open_manipulator 5.0.0 필수 — 켜둔 채로 두기)
rosenv    # settings.md 1.5의 alias (RMW_IMPLEMENTATION 포함)
ros2 run rmw_zenoh_cpp rmw_zenohd

# 터미널 1: 로봇 bringup
rosenv
ros2 launch open_manipulator_bringup omx_f.launch.py port_name:=/dev/ttyACM0

# 터미널 2: MoveIt + RViz (EE를 움직일 조종간)
rosenv
ros2 launch open_manipulator_moveit_config omx_f_moveit.launch.py

# 터미널 3: EE 좌표 실시간 출력
rosenv
ros2 run tf2_ros tf2_echo world end_effector_link
# 출력 예:  - Translation: [0.213, 0.005, 0.087]   ← [x, y, z] (m)
```

1. RViz에서 EE의 **interactive marker**(주황 공)를 드래그 → 작업대 위 안전 높이(면에서 3~5cm 위)로 목표 설정 → **Plan & Execute**
2. 목표 z를 **1cm → 5mm 단위로 낮춰가며** 반복 실행 — 그리퍼 끝이 작업대 면에 **살짝 닿는 순간 멈춤** (밀어붙이지 말 것)
3. 터미널 3의 Translation **z값을 기록 — 이 값이 그대로 `TABLE_Z`** (추가 계산 없음)
4. **TABLE_Z의 의미**: 그리퍼 끝이 작업대에 닿는 순간의 end_effector_link z값:
   - 끝단을 작업대에 닿게 → 로봇에 `z = TABLE_Z` 명령
   - 끝단을 2cm 위로 → `z = TABLE_Z + 0.02`
   - ⚠️ 단, **측정 때의 그리퍼 자세(수직 아래)와 실제 작업 때의 자세가 같아야함**
5. 검산: 작업대 위 **다른 위치 한 곳** 더 터치해서 TABLE_Z가 ±2~3mm 안에서 재현되는지 확인 (작업대 기울어짐도 이때 발견됨)
6. **그리퍼 교체·재조립 시 TABLE_Z 재측정 필수** — 끝단 기하가 바뀌면 "닿는 순간의 링크 z"도 바뀜 (터치 1회, 5분). 장착 방식·모터 방향이 달라져도 end_effector_link는 link5 기준 가상 프레임이라 FK는 그대로 정확하고, H·마커 좌표도 그리퍼와 무관하니 **TABLE_Z만** 다시 재면 됨

> 토크 오프(손으로 밀어서 터치)가 가능하면 1~2단계를 대체할 수 있음 — `ros2 service list | grep -i torque`로 해당 버전에 토크 제어 서비스가 있는지 확인 후 사용. 없으면 위 RViz 방식이 확실함.


## 4. H_bag(봉투 거치대)용 추가 준비

- 마커를 개구부 위치(거치대) 평면에 부착하고 위 2~3 절차 반복
- world 좌표는 `marker_world_bag.json`에 별도 기록
- 개구부 평면 높이를 `--z`로 사용 (예: 0.15)

<br/>
<br/>

# 실행

> WSL, `conda activate lerobot` 환경에서. 카메라는 `usbipd attach` 완료 상태여야 함 (`ls /dev/video*` 확인) — 공통 절차는 [settings.md](../../docs/00_environment_settings.md) "2. 매번 하는 것" 참조.

## 1단계 — 검출 확인 (H 저장 전 반드시)

```bash
python aruco_homography.py --world marker_world_table.json --camera 0 \
  --check-only --save-annotated check.jpg
```

| 옵션 | 값 의미 |
|---|---|
| `--world` | 위에서 실측·기록한 마커 world 좌표 JSON |
| `--camera` | 카메라 index — `lerobot-find-cameras opencv`로 확인한 값 |
| `--check-only` | H 저장 없이 검출·오차만 출력 |
| `--save-annotated` | 검출 위치를 그린 이미지 저장 (선택) |

- 출력의 `검출된 마커: [0, 1, 2, 3]` — 4개 전부 나와야 함. 빠지면 조명/가림/초점 확인
- `check.jpg` 열어서 빨간 점이 마커 중심에 정확히 찍혔는지 눈으로 확인

## 2단계 — H 생성

```bash
# 작업대용
python aruco_homography.py --world marker_world_table.json --camera 0 \
  --output H_table.json --z 0.0

# 봉투 거치대용 (마커 재부착·재실측 후)
python aruco_homography.py --world marker_world_bag.json --camera 0 \
  --output H_bag.json --z 0.15
```

| 옵션 | 값 의미 |
|---|---|
| `--output` | 저장할 H JSON 파일명 |
| `--z` | 이 평면의 높이 (로봇 베이스 기준 m) — 작업대는 실측한 `TABLE_Z`, 봉투는 개구부 평면 높이. H 계산엔 안 쓰이고 메타데이터로 저장되어 `PlaneTransform.plane_z`로 읽힘 |

- 출력되는 **재투영 오차(픽셀)**: 평균 1~2px 이내 양호, **5px 초과 시 경고** → 부착 평평함·실측값 재확인

## 3단계 — (Trouble Shooting) 렌즈 왜곡 보정

> 1~2단계 후 아래 "검증"에서 오차가 ±1cm 안이면 안 해도 됨
> 검증 오차가 클 때(특히 이미지 **가장자리**에서) 하기

**3-1. 내부파라미터(K·dist) 측정** — 카메라당 1회, 카메라를 옮겨도 유효:

```bash
python checkerboard_intrinsics.py --pattern 9x6 --square 0.025 --camera 0 \
  --output intrinsics.json
```

| 옵션 | 값 의미 |
|---|---|
| `--pattern` | 체커보드 **내부 코너** 수 (칸 수 아님 — 10×7칸 보드 = 9x6 코너) |
| `--square` | 정사각형 한 변 실측 길이(m) — 인쇄 후 자로 잰 값 (예: 2.5cm → 0.025) |

- 라이브 창에서 `board: OK` 표시될 때 **SPACE**로 캡처, 다양한 각도·거리로 15~30장, **q**로 종료·계산
- RMS 오차 기준: **0.5px 이하 우수 / 1.0px 이하 사용 가능 / 초과 시 재촬영**

**3-2. 왜곡 보정 반영해서 1~2단계 재실행** — `--intrinsics`만 추가하면 됨:

```bash
python aruco_homography.py --world marker_world_table.json --camera 0 \
  --intrinsics intrinsics.json --check-only
python aruco_homography.py --world marker_world_table.json --camera 0 \
  --intrinsics intrinsics.json --output H_table.json --z 0.0
```

이후 아래 "검증"도 다시 수행.


**3-3. 런타임 비전 맞추기**

- `--intrinsics`로 만든 H는 "왜곡을 편 이미지" 기준이므로, 이 H를 쓰는 쪽(봉지 검출, CPN grasp point)도 `cv2.undistort(frame, K, dist)` 한 이미지에서 픽셀을 뽑아야 함
- 섞으면(H는 보정, 픽셀은 원본) 오히려 오차 증가. H JSON의 `"undistorted": true` 필드로 어느 기준인지 확인 가능.


<br/>
<br/>

# 검증

## 알려진 점 역산

마커 0의 중심 픽셀 좌표(1단계 `check.jpg` 또는 H JSON의 `marker_pixels` 값)를 넣어보면:

```bash
python -m common.pixel_to_world --h calibration/camera/H_table.json --uv <마커0_u> <마커0_v>
```

→ 출력이 `marker_world_table.json`에 적은 마커 0의 (x, y)와 **±수 mm 이내**면 정상.

## 새로운 점 실측 대조 

1. 작업대 위 임의 위치에 작은 물체(지우개 등)를 놓는다
2. 카메라 이미지에서 물체 중심 픽셀 (u, v)를 읽는다 (`--save-annotated`로 캡처한 이미지를 열어 확인)
3. `python -m common.pixel_to_world --h H_table.json --uv <u> <v>` 로 변환
4. 줄자로 실측한 물체 위치와 비교 → **±1cm 이내면 시연용으로 충분**

## 로봇 이동 최종 확인 

변환된 world 좌표로 로봇 EE를 이동시켜 (MoveIt2 또는 ikpy) 물체 위에 정확히 도달하는지 확인, 통과되면 vision → motion 파이프라인 완료

**⚠️ 첫 실행 마진 규칙 (z 사고 방지):** z를 정확히 쟀더라도 처음 보낼 땐 **목표 z + 2~3cm 위**를 목표로 이동 → 육안으로 위치 확인 → 1cm씩 단계적으로 낮추기. 그리퍼가 작업대에 닿기 전에 항상 멈출 수 있는 높이에서 시작할 것. (z 오측정 시: 낮으면 그리퍼 파손, 높으면 파지 실패 — 낮은 쪽이 위험)

## 오차가 클 때 점검 순서

1. 마커가 들뜨거나 휘지 않았는지 (평평함이 가장 흔한 원인)
2. `marker_world.json` 실측값 오타·단위(m) 확인
3. 마커 4개가 거의 일직선 배치는 아닌지 → 사각형으로 재배치
4. 카메라가 흔들렸으면 처음부터 재실행 (H는 카메라 위치·각도에 종속)

<br/>

---

<br/>

## 사용처

이 폴더에서 만든 H·K·dist는 `common/pixel_to_world.py`(`PlaneTransform`)에서 로드되어 `rule_based/`의 시퀀서에서 호출된다.

```python
from common.pixel_to_world import PlaneTransform
tf = PlaneTransform.load("calibration/camera/H_table.json")
x, y = tf.pixel_to_world(u, v)     # 비전이 준 픽셀 → 로봇 world 좌표
z = tf.plane_z                     # H 생성 시 --z 로 넣은 평면 높이
```

## 주의

- 마커 부착 위치가 바뀌거나, **카메라를 다시 장착/이동하면 재캘리 필수** (H는 카메라 pose에 종속)
- 카메라 높이·각도 바뀌면 H도 다시
- z축 움직임은 옷을 들어 올릴 때만 사용하는 가정 — 평면 가정이 깨지는 높이에서는 H 사용 불가
- 결과 JSON(`H_*.json`)에는 생성 당시 마커 픽셀·world 좌표·오차가 메타데이터로 저장됨 → 나중에 이상하면 이 값으로 원인 추적

<br/>

---

<br/>

# 참고 — 로봇 터치 방식 (robot_touch_homography.py)

마커 인쇄·부착·줄자 실측 없이, **로봇 EE가 평면을 직접 터치한 위치**를 대응점으로 쓰는 대안. world 좌표를 FK에서 읽으므로 자가 필요 없다.

## 사전 준비

1. **FK 좌표를 읽을 수단** — 둘 중 하나:
   - **ROS2 (권장)**: 터미널 별도로 띄워서
     ```bash
     # 각 터미널에서 rosenv 먼저 (settings.md 1.5 alias)
     ros2 run rmw_zenoh_cpp rmw_zenohd                                              # 터미널 0 (5.0.0 필수, 켜둔 채로)
     ros2 launch open_manipulator_bringup omx_f.launch.py port_name:=/dev/ttyACM0   # 터미널 1
     ros2 run tf2_ros tf2_echo world end_effector_link                              # 터미널 2 (좌표 실시간 출력)
     ```
   - ROS2가 부담이면: 자주 쓰는 지점 몇 곳만 줄자로 실측해서 입력해도 됨 (그러면 ArUco 방식과 정확도 차이 없음)
2. **터치 자세는 항상 수직 아래로 통일** — `tf2_echo`는 `end_effector_link`(장착부) 좌표를 주는데, 그리퍼가 수직 아래를 향하면 끝단이 링크 바로 밑에 있어서 **(x, y)는 링크값을 그대로 쓰면 됨** (별도 보정 불필요). 비스듬히 터치하면 끝단 (x,y)가 링크에서 수평으로 어긋나므로 금지
3. 카메라는 평소 위치에 고정, `usbipd attach` 완료 상태

## 절차

```bash
python robot_touch_homography.py --camera 0 --output H_table.json --z 0.0
```

| 키 | 동작 |
|---|---|
| `SPACE` | 현재 프레임 정지 → 터치 지점 마우스 클릭 대기 |
| (클릭 후) | 터미널에 FK world 좌표 `x y` 입력 (m 단위) |
| `r` | 마지막 점 취소 |
| `c` | 4점 이상 모이면 H 계산·저장 |
| `q` | 중단 (저장 안 함) |

점별 반복 흐름:

1. 로봇을 **토크 오프**(손으로 밀기) 또는 teleop으로 움직여 평면 위 한 지점을 EE 끝으로 터치, 그대로 정지
2. `tf2_echo` 출력에서 지금 (x, y) 읽어두기 (TCP 오프셋 보정)
3. 스크립트 창에서 `SPACE` → 화면 정지 → **EE가 닿은 지점**을 마우스로 클릭
4. 터미널에 `x y` 입력
5. **4점 이상** 반복 — 점들은 서로 멀리, **일직선 금지** (작업 영역 네 귀퉁이 근처 권장)
6. `c` → 재투영 오차 확인 → JSON 저장

## 검증

출력 JSON 형식이 ArUco 방식과 동일하므로(`H`, `plane_z`) **위의 "완료 후 검증" 1~3을 그대로 사용**하면 된다.
검증 1의 정답지는 마커 대신 **터치했던 점** — JSON의 `points` 배열에 픽셀·world 쌍이 저장돼 있다.

## ArUco 방식과 선택 기준

- 프린터 있고 카메라가 작업대 전체를 보는 상태 → **ArUco** (반복 재캘리 편함)
- 프린터 없거나, 마커 붙일 자리가 없거나, ROS2 FK가 이미 떠 있는 상태 → **로봇 터치**
- 정확도는 둘 다 대응점 품질에 좌우 — 터치 방식은 **TCP 오프셋 보정 실수**가 최대 오차 원인이니 주의

<br/>

---

<br/>

# 참고 — RViz로 좌표축 확인

**RViz:** ROS의 3D 시각화 도구. 로봇 URDF 모델을 실제 관절 각도로 렌더링하고, 각 링크의 좌표축(TF)을 화살표로 표시 (**빨강=x, 초록=y, 파랑=z**). 물리 시뮬레이터가 아니라 "보기 전용" 뷰어 (물리 시뮬은 Gazebo 담당).

## 사전 셋팅 (필요 조건)

> 카메라 캘리브레이션 자체(aruco_homography 등)에는 RViz가 **필요 없음** — 축 방향 확인/로봇 터치 방식에서만 사용.

- ROS2 Jazzy + MoveIt + open_manipulator 빌드: [settings.md](../../docs/00_environment_settings.md) **1.5** 참조 (Zenoh·WSLg 주의사항 포함)
- 로봇 USB 연결: settings.md "2. 매번 하는 것" — 로봇 없이 모델만 보려면 bringup에 `use_mock_hardware:=true`
- ⚠️ **LeRobot(teleop/record)과 ROS2 bringup은 같은 포트 동시 사용 불가** — 하나만 실행

## 실행

```bash
# 터미널 0: Zenoh 라우터 (5.0.0 필수 — 켜둔 채로 두기)
rosenv    # ROS 환경 로드 alias — 없으면 settings.md 1.5의 "alias 등록" 참조
ros2 run rmw_zenoh_cpp rmw_zenohd

# 터미널 1: 로봇 bringup — 모터와 시리얼 통신 시작, 관절각·TF 발행 (실물 로봇 연결층)
rosenv
ros2 launch open_manipulator_bringup omx_f.launch.py port_name:=/dev/ttyACM0

# 터미널 2: MoveIt(모션 플래닝) + RViz(3D 뷰) — 자동으로 RViz 창이 뜸
rosenv
ros2 launch open_manipulator_moveit_config omx_f_moveit.launch.py
```

축 보는 조작법은 위 "3. world 좌표 실측"의 **RViz에서 축 보는 법** 참조.

<br/>

---

<br/>

# 참고 — teleop 기록 + 오프라인 FK 방식 (TABLE_Z 측정 대안)

RViz 방식 대신, **Leader로 Follower를 직접 끌어서 터치**하고 그 순간의 관절각을 기록해 나중에 z를 계산하는 방법. ROS2 없이 LeRobot만으로 가능하다.

## 원리

포트 충돌 때문에 "터치(teleop)"와 "좌표 읽기(tf2_echo)"를 동시에 못 하니, 시간을 분리한다:

```
[현장]  teleop --log_csv 로 터치 → 터치 순간의 관절각이 CSV에 저장됨
[나중]  CSV의 관절각 → FK 계산 → EE의 (x, y, z) 역산 → TABLE_Z
```

## 절차 (개요)

1. `lerobot-teleoperate ... --log_csv touch_log.csv` 실행 (팀 fork에 포함된 옵션)
2. Leader를 조작해 Follower EE 끝을 작업대 면에 살짝 터치, **2~3초 정지** (CSV에서 그 구간을 찾기 쉽게)
3. teleop 종료 → `touch_log.csv`에서 정지 구간의 관절각 행을 찾음
4. 관절각 → FK: lerobot 내장 `model/kinematics.py`의 `RobotKinematics`(placo 기반) 사용
5. 나온 z + TCP 오프셋 보정(`− L_tip`, 수직 자세 기준) = `TABLE_Z`

## 현재 상태

- ⚠️ **4번 FK 계산 스크립트는 미구현** — CSV 관절각을 읽어 `RobotKinematics`로 EE pose를 뽑는 코드를 짜야 함 (필요해지면 `common/`에 추가 예정)
- 1회성 TABLE_Z 측정이면 RViz 방식이 더 빠름. 이 방식이 유리해지는 경우: **여러 점을 반복 터치**해야 할 때(로봇 터치 Homography를 ROS2 없이 하고 싶을 때), ROS2 셋업이 안 된 컴퓨터에서 작업할 때
