# inspection — YOLO 양면 외관 검수 (INS-01)

정면 Inspection Camera(ESP32-S3-CAM) 영상에서 이염, 얼룩, 찢김을 검출하고 Face A와 Face B 결과를 통합해 **재판매 가능 / 추가 확인 필요**로 판정한다.

```
Face A 프레임 ─┐
               ├─ YoloInspector.inspect() ─ InspectionResult(side, passed, valid, defects)
Face B 프레임 ─┘                                   │
                                   ResultIntegrator.integrate() ─ IntegratedResult(decision, reason)
```

## 파일

| 파일 | 역할 |
|---|---|
| `inspector.py` | YOLO 가중치 로드, 한 면 검수, 결과 오버레이·JSON 저장 |
| `integrator.py` | Face A/B 통합. 시야 미확보, 결함 검출, 불확실 검출은 모두 추가 확인 필요로 분류 |
| `esp32_frame_source.py` | ESP32-S3-CAM UDP(JPEG 1프레임 = 1패킷) 수신기. 최신 프레임 1장 제공 |
| `run_inspection.py` | CLI. 이미지 파일 또는 ESP32 실시간으로 한 면/양면 검수 |

## 판정 규칙

| 조건 | 판정 |
|---|---|
| 양면 모두 시야 확보, 검출 0건 | 재판매 가능 |
| 어느 한 면이라도 의류 영역 비율 < `min_garment_area_ratio` | 추가 확인 필요 (시야 미확보) |
| confidence ≥ `--conf`(기본 0.5) 인 검출 존재 | 추가 확인 필요 (이상 검출) |
| `--uncertain-lo`(기본 0.35) ≤ confidence < `--conf` 인 검출 존재 | 추가 확인 필요 (판정 불확실) |

정상으로 강제 확정하지 않고 False Negative를 줄이는 보수적 정책이다.

## 실행

```bash
pip install -r inspection/requirements.txt
# 저장 이미지
python -m inspection.run_inspection --weights weights/yolo_garment_defect.pt --image faceA.jpg --side A
# ESP32-S3-CAM 실시간 양면 (setup/camera/esp32-cam 펌웨어 기준, UDP 8001)
python -m inspection.run_inspection --weights weights/yolo_garment_defect.pt --esp32 --both
```

결과는 `outputs/inspection/<timestamp>_face<A|B>.json` 과 오버레이 `.jpg`로 저장된다. `ui/`는 현재 저장 영상 기반 시연용이라 이 JSON을 읽는 어댑터는 아직 연결되지 않았다.

## 가중치와 데이터

- 클래스: `stain`(얼룩), `discoloration`(이염), `tear`(찢김). 가중치 `.pt`는 용량 문제로 저장소에 포함하지 않는다.
- 데이터는 결함 크기와 위치, 의류 색상, 조명, 주름, 카메라 거리 변화를 포함하고, 같은 원본의 augmentation이 train과 test에 섞이지 않도록 제품 또는 촬영 세션 단위로 분할한다.
- 평가는 mAP@0.5, mAP@0.5:0.95, Precision, Recall, F1에 더해 클래스별 Recall을 따로 관리한다.
