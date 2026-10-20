# 4-Bar Parallel Gripper (Follower)

이 폴더는 OMX-AI Follower arm의 부품을 기반으로 구성한 rigid parallel gripper 파일을 정리한 공간입니다.

## 파일
```
- stp_file                     # stl 파일에 대한 step 파일 + OMX-AI(Follower)
- gripper_link.stl             # mount bracket과 finger 연결부 (2개 필요)
- motor_case.stl               # 모터 케이스
- motor_mount_bracket.stl      # 마운트 브래킷
- parallel_gripper_finger.stl  # 그리퍼 핑거 (2개 필요)
- parallel_gripper_mover.stl   # 그리퍼 핑거와 연결부 (2개 필요)
- spacer.stl                   # 스페이서 (4개 필요)
```

## 설계 방향

- 기존 회전형 그리퍼로는 의류처럼 부드러운 재질을 파지할 때 미끄러지거나 놓치는 문제가 발생하여, 손끝이 항상 평행을 유지하는 4-Bar 링크 구조로 설계하였고, 고무를 끼울 수 있도록 설계
- `parallel_gripper_mover`가 모터 회전을 finger의 평행 개폐 동작으로 변환하여, 접촉 표면에 압력을 균일하게 분산시킴
- `gripper_link`로 mount bracket과 finger를 연결하고, `spacer`로 각 링크 사이 간격과 정렬을 확보
- 전용 모터(Dynamixel) 사양에 맞춰 원단을 집기에 충분한 개구량(Open Size)을 확보할 수 있도록 구조 최적화
- 반대편 그리퍼와 의류 양끝단을 동시에 맞잡아 원단을 주름 없이 평평하게 펼치고, 비전 카메라가 오염·훼손 부위를 정확하게 탐지할 수 있도록 finger 구조를 설계