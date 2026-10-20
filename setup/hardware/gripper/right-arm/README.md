# SSG Soft Finger & Parallel Gripper (Leader)

이 폴더는 SSG-style soft finger 및 parallel gripper 파일을 정리한 공간입니다.

## 파일
```
- stp_file                   # stl 파일에 대한 step 파일 + OMX-AI(Leader)
- pole.stl                   # 그리퍼를 끼우기 위한 봉 (2개 필요)
- rack_gear.stl              # 그리퍼 움직이기 위한 랙 기어 (2개 필요)
- soft_gripper.stl           # SSG 스타일 soft finger (2개 필요)
- spur_gear.stl              # 톱니바퀴
```

## 설계 방향

- SO-ARM101 + SSG48 Soft Gripper 구성을 기반으로, 비닐 패키지를 안정적으로 벌려 고정하는 역할을 담당합니다.
- SSG-48 전체 그리퍼를 그대로 사용하는 것이 아니라, SSG-style soft finger 형상만 참고해 `soft_gripper`를 구성합니다.
- 기존 rigid finger 소재를 TPU95A Soft 소재로 교체하여, 비닐 파지 시 미끄러짐을 방지하고 Compliant한 접촉이 가능하도록 합니다.
- `pole`에 `soft_gripper`를 끼우고 `rack_gear`·`spur_gear`의 랙-피니언 구동으로 두 finger를 평행하게 개폐합니다.
- 현재 Gazebo 시뮬레이션 환경에서 동작 검증을 완료했습니다.
- 이 STL 파일들은 3D 모델 공유와 출력 검토를 위한 파일입니다.
