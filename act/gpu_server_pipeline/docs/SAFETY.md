# Safety boundary

이 프로젝트는 연구용 soft-real-time remote inference 예제이며 safety-certified robot
controller가 아닙니다. 작업자는 물리 전원 차단 수단과 전체 swept volume을 관리해야
합니다.

기본값은 dry-run이고 task-specific gripper hold는 꺼져 있습니다. 실제 구동은 다음을
동시에 요구합니다.

- audited action/state JSON과 recorded start pose
- `ARM_REAL_HARDWARE=I_UNDERSTAND_THIS_MOVES_OMX`
- interactive `MOVE OMX`
- controller subscriber 1, 기존 command publisher 0

감시는 “단 한 번의 WSL/Dynamixel 누락”을 즉시 fatal로 보지 않습니다. source timestamp
기준 rolling window에서 loss 비율을 평가하고, 짧은 수신 pause에는 새 action 발행을
멈추고 fresh observation/chunk로 재동기화합니다. 기본 hard loss는 20%이며 profile에서
조정할 수 있습니다. 반면 voltage, encoder, electrical shock, overload 같은 hardware
error status는 데이터 누락이 아니므로 즉시 중지합니다.

센서가 끊겼을 때 관절 action을 임의 interpolation하지 않습니다. 오프라인 dataset
변환의 bounded interpolation과 달리 실제 구동에서는 미래 표본이 없고 잘못된 외삽이
위험하기 때문입니다.

`MAX_EXECUTED_ACTIONS`를 설정하지 않으면 긴 작업을 위한 총 실행시간 제한은 없습니다.
다만 통신·센서 freshness와 절대/상대 관절범위는 계속 확인합니다. 이 제약은 ACT의
행동을 재설계하는 임의 filter가 아니라 stale command와 명백한 범위 이탈을 막는
runtime contract입니다.

Bundled `in-package-socks`의 gripper hold는 학습된 닫힘 구간에서 target position을
유지하기 위한 task-specific 보완입니다. 모터 current/torque를 데이터셋이 직접 학습한
것은 아니며, 다른 gripper나 물체에는 그대로 적용하지 않습니다.
