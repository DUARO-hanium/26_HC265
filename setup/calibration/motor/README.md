# calibration/motor — Dynamixel 모터 pulse ↔ 관절각 매핑

**목적:** 모터의 pulse 값(0~4095)을 실제 관절각과 대응시킨다. 안 하면 teleop 매핑이 틀어지고 수집 데이터가 오염되어 replay/ACT 전부 부정확해진다.

**언제 필요:** teleop / record / replay / ACT / rule-base **모든 경로**에서 필요.

**특히 재캘리 필수:** **그리퍼 교체 시.** DUARO는 커스텀 4절 평행 그리퍼(Follower)와 SSG48 소프트 그리퍼(Leader)로 교체했으므로 gripper min/max pulse가 기본값과 다름. 재캘리 없으면 덜 닫히거나 과폐가 발생.

## 사전 준비 (매번)

[settings.md](../../docs/00_environment_settings.md) "2. 매번 하는 것" — usbipd attach + `lerobot-find-port`로 포트 확인 (카메라 불필요).

## 실행

**Follower:**
```bash
bash calibrate.sh follower
```

**Leader:**
```bash
bash calibrate.sh leader
```

## 작동 순서 (수동)

1. 로봇 중립 자세로 놓고 `Enter` → 영점 기록
2. 각 관절 가동 범위 끝까지 움직임 → min/max pulse 기록 (gripper는 열림·닫힘 왕복)
3. 완료 시 JSON 저장, 이후 teleop/record 실행 시 자동 적용

## 결과물

`~/lerobot/src/lerobot/robots/omx_follower/calibration/omx_follower_arm.json`
`~/lerobot/src/lerobot/teleoperators/omx_leader/calibration/omx_leader_arm.json`

JSON은 각 모터별 `{id, drive_mode, homing_offset, range_min, range_max}` 구조 (관절 6개 + gripper).

**이력 관리:** 재캘리 할 때마다 결과 JSON을 이 폴더에 날짜 태그 붙여 사본 저장. 예:
```
calibration/motor/
├── omx_follower_arm_2026-07-27.json
├── omx_leader_arm_2026-07-27.json
└── history.md    # 변경 사유·그리퍼 버전 기록
```

## 주의

- `--robot.id` 통일 유지 (id 바꾸면 새 캘리 요구됨)
- 캘리브레이션 다시 수행하면 **이전에 수집한 데이터가 무의미해질 수 있음**
- 포트 항상 `lerobot-find-port`로 확인
