# grasp — 검수 지향 파지점 추론과 로봇팔 파지 동작

턴테이블 회전 후 작업대 위 의류에서 **검수면을 넓게 펼칠 수 있는 파지점 쌍**을 찾고, 양팔이 그 좌표로 가서 잡아 들어올린다.

| 폴더 | 내용 | 원본 저장소 |
|---|---|---|
| `vision/` | Arducam → ROS → SAM 의류 마스크 → FashionAI 어깨/밑단 좌표와 점수 → 통과 시 GRASP 후보, 미달 시 마스크 주축 기반 UNFOLD(재배치) 후보 | `garment-vision-pipeline` |
| `motion/` | 베이스(`link0`) 기준 (x, y, z)를 주면 목표 위 6 cm 접근 → 수직 하강 → 처짐 보정 → 그리퍼 닫기 → 파지 판정 → 들기. MoveIt 없이 직접 IK | `omx-robot-motion` |
| `moveit_scripts/` | MoveIt2 기반 봉지 진입 계획, go_home / move_to_xyz / gripper / pick_and_place 스크립트 | `OMX-Setup-Guide/src` |

## 흐름

```
Vision Camera 프레임
  └─ SAM mask (fal.ai SAM3)
      └─ FashionAI CPN keypoint + heatmap score
          └─ Feasibility: score ≥ 임계, mask 내부, 경계 margin, 두 점 간 거리, 좌우 reachability
              ├─ 통과 → GRASP (u,v) 쌍 → setup/calibration 로 (x,y,z) 변환 → motion/go_down.py --both
              └─ 미달 → UNFOLD 후보 → 양팔 소폭 들어 저속 재배치 → 재관찰 (폐루프)
```

전개 폭은 SAM mask 기준 실제 유효 폭 W에 대해 `d_target ≤ 0.95 W`로 제한한다.

## 실행

```bash
# 1. Vision Camera 발행
cd grasp/vision && ARDUCAM_ROTATE=none bash ./run_gscam_b0196.sh realtime
# 2. 파지점 추론 (FAL_KEY 는 환경 변수로만)
cd grasp/vision/deep_fashion/fashionai-key-points-detection
bash ./run_garment_inspection_mvp.sh --ros-topic /camera1/image_raw --clothing-type blouse --sam3-prompt shirt
# 3. 로봇팔 (dry-run 후 --execute)
cd grasp/motion && python3 go_down.py --arm single --xyz 0.18 0.00 0.10 --correct 2 --execute
```

`vision/`이 출력하는 좌표는 픽셀 (u, v)이다. 로봇 좌표로 바꾸려면 `setup/calibration/`의 호모그래피 또는 hand-eye 결과가 필요하며, `motion/coord_conversion/`에 변환 결과가 없을 때 쓰는 대체 경로가 있다.
