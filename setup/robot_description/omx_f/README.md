# convert_urdf — OMX-AI Follower URDF (커스텀 그리퍼 반영)

**목적:** 커스텀 그리퍼를 반영한 URDF 만들기. 공식 URDF의 조인트 구조는 검증돼 있으므로 **전체를 새로 만들지 않고, 그리퍼 관련 링크만 교체·수정**한다.

**출처:** ROBOTIS `open_manipulator_description` 패키지 (`OMX-LeRobot-Setup_v1/docs/open_manipulator/`)에서 follower(`omx_f`) 부분만 복사.

## 파일 구성

| 파일 | 내용 |
|---|---|
| `omx_f.urdf` | 공식 원본 그대로 (`package://` 경로 — ROS 패키지 안에서만 로드됨) |
| `omx_f_local.urdf` | 메쉬 경로만 상대경로로 바꾼 사본 — **ROS 밖 도구(시뮬레이터·FK 라이브러리)는 이걸 사용** |
| `meshes/omx_f/*.stl` | 링크별 메쉬 8개 (mm 단위 → URDF에서 `scale 0.001`로 보정) |
| `xacro/` | 원본 xacro 소스 (참고용 — 직접 수정은 .urdf에 하면 됨) |

## URDF 구조 — 수정 대상

링크 체인: `world → link0(베이스) → link1~5(팔) → link6·7(그리퍼 손가락)`

| 위치 (omx_f.urdf) | 내용 | 커스텀 그리퍼 시 |
|---|---|---|
| `link6` (227행) | 모터 쪽 손가락 — `follower_07_gripper_motorized.stl` | 메쉬 교체 + 질량 갱신 |
| `link7` (261행) | 기어 쪽 손가락 — `follower_08_gripper_gear.stl` | 메쉬 교체 + 질량 갱신 |
| `gripper_joint_1` (219행) | 손가락 회전 조인트 (axis z) | 피벗 위치 그대로면 수정 불필요, 벌어짐 각도 바뀌면 `limit`만 |
| `gripper_joint_2` (252행) | 반대 손가락 — `mimic multiplier="-1"`로 joint_1에 연동 | 〃 |
| `end_effector_joint` (13행) | TCP(파지 기준점) — link5 기준 `xyz="0.09193 -0.0016 0"` | 파지 지점 바뀌었으면 이 값 수정 |

## 수정 절차

1. **Fusion에서 커스텀 손가락 STL 내보내기** — 링크(움직이는 단위)별로 따로. **원점을 기존 부품과 동일한 피벗 기준으로** 맞춘 뒤 내보낼 것 (기존 STL을 Fusion에 불러와 겹쳐 보고 확인). 단위는 mm 그대로 두면 됨 (URDF의 `scale="0.001"`이 처리)
2. **메쉬 교체** — `meshes/omx_f/`에 STL 추가 후, link6·7의 `<visual>`·`<collision>` 안 `filename`을 새 파일명으로 변경 (`omx_f.urdf`·`omx_f_local.urdf` 둘 다)
3. **질량 갱신** — 출력물+나사 조립 상태로 저울 실측 → `<inertial>`의 `<mass>`에 입력 (kg 단위). CAD 계산값은 infill 때문에 실제보다 무거움
4. **관성텐서 갱신** — 형상 변화가 작으면: 기존 값 × (실측질량/기존질량). 크면: Fusion에서 STEP에 밀도 지정 → 물성치의 관성 모멘트 읽어서 입력
5. **TCP 확인** — 손가락 길이·파지 지점이 바뀌었으면 `end_effector_joint`의 `xyz` 조정

## 검증

```bash
# ROS2 (rosenv) — RViz에서 육안 확인: 메쉬 위치·손가락 개폐·TCP(빨간 박스) 위치
ros2 launch open_manipulator_bringup omx_f.launch.py use_mock_hardware:=true
```

ROS 없이 빠르게 보려면 (`conda activate lerobot`):

```bash
pip install yourdfpy
python -c "import yourdfpy; yourdfpy.URDF.load('omx_f_local.urdf').show()"
```

- 체크: 새 메쉬가 link5 끝에 제대로 붙는가 / 손가락 두 개가 반대로 연동되는가 / 스케일이 1000배 크거나 작지 않은가

## 주의

- **단위**: Fusion STL은 mm, URDF는 m — `scale="0.001 0.001 0.001"` 누락하면 로봇이 1000배 커짐
- **원점 불일치가 최다 오류** — 메쉬가 엉뚱한 곳에 떠 있으면 STL 내보내기 원점부터 의심
- `omx_f.urdf`와 `omx_f_local.urdf` **두 파일에 동일하게 반영** (경로 빼고 내용 같아야 함)
- 원본 xacro에서 재생성하면 수정이 덮어써짐 — 이 폴더의 .urdf가 기준
- **그리퍼 교체 후 `TABLE_Z` 재측정 필수** — [calibration/homography](../../calibration/homography/README.md) "TABLE_Z 측정" 참조 (끝단 기하가 바뀌면 닿는 높이도 바뀜)
