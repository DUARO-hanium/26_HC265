# process_controller — 공정 상태 제어 (PCS-01)

반품 패키지 하나가 들어와 분류 바구니에 들어갈 때까지의 12단계 상태머신과 S/W Interlock.
AI 출력이 곧바로 액추에이터 명령이 되지 않도록 **상태 검증 → 물리 실행 가능성 확인 → 실행** 순서를 강제한다.

```
Idle → Package Detection → Package Manipulation → Product Extraction → Workspace Switching
     → Garment Reconfiguration ⟲ → Face A Inspection → Surface Switching → Face B Inspection
     → Result Integration → Sorting → Completed
```

## 파일

| 파일 | 역할 |
|---|---|
| `states.py` | 상태 12종 + ERROR, 공정별 Z축 높이 이름, 허용 전환표 |
| `interfaces.py` | 하위 모듈 Protocol (ArmPolicy, AuxAxes, GraspVision, ArmMotion, Inspector, Monitor) |
| `interlock.py` | 턴테이블 / Z축 / 검수 / 분류 허용 조건 검사 |
| `controller.py` | 상태별 처리와 전환, 재배치 상한, 정책 재시도, 사이클 로그 저장 |

## Interlock 조건

| 동작 | 허용 조건 |
|---|---|
| 턴테이블 180° | 제품 인출 완료, 양팔 Safe Pose, Z축 Safe Height |
| Z축 높이 변경 | 해당 공정 종료, 팔 정지 |
| Face 검수 | Inspection Height 도달, 팔 정지(영상 안정) |
| 분류 | Face A/B 결과 통합 완료 |

## 하위 모듈 연결

| Protocol | 구현 위치 |
|---|---|
| `ArmPolicy` | `act/dualarm_inference` (왼팔 개구부, 오른팔 인출 순차 추론) |
| `AuxAxes` | `rdk/` (`lift_axis.py`, `turn_axis.py`, `poses.csv` 의 높이 프리셋) |
| `GraspVision` | `grasp/vision` (SAM + FashionAI, GRASP/UNFOLD 후보) + `setup/calibration` 좌표 변환 |
| `ArmMotion` | `grasp/motion/go_down.py` (좌표 접근, 하강, 파지, 들기) |
| `Inspector` | `inspection/` (`YoloInspector`, `ResultIntegrator`) |
| `Monitor` | `ui/` (읽기 전용 Monitoring Layer) |

각 Protocol 을 구현한 어댑터를 `ProcessController` 에 주입하면 `run_once()` 가 한 사이클을 실행하고 `outputs/cycles/cycle_XXXX.json` 에 이력을 남긴다.

```python
from process_controller import ProcessController, ControllerConfig

pcs = ProcessController(policy, aux, vision, motion, inspector, monitor, ControllerConfig(max_reconfiguration=3))
pcs.run_once()
```
