# Architecture and contracts

```text
Windows camera1 wrist ─UDP5000─┐
Windows camera2 external ─5002─┤
                               ▼
                    WSL ROS 2 Fast DDS graph
                    /joint_states + compressed images
                               │ LeRobot observations
                               ▼
                    official async inference client
                               │ gRPC over SSH tunnel/VPN
                               ▼
                    GPU official PolicyServer + ACT
                               │ action chunks
                               ▼
                    ROS adapter /leader/joint_trajectory
                               │
                               ▼
                    OMX follower ros2_control
```

Dataset와 runtime의 고정 contract는 30 FPS, RGB 640x480 두 대, 6차원 state/action,
`joint1..joint5, gripper_joint_1` 순서입니다. camera1은 손목, camera2는 외부입니다.
역할을 바꾸면 tensor shape가 같아도 학습 의미가 깨집니다.

학습은 LeRobot 0.6.0의 `lerobot-train`을 Accelerate로 실행합니다. Remote inference는
LeRobot 0.6.0 `lerobot.async_inference.policy_server`와 client를 사용하며, 저장소 코드는
ROS message와 LeRobot observation/action contract를 연결하는 plugin입니다.

데이터 수집용 Zenoh 설정은 별도 흐름입니다. Live inference 스크립트는 로컬 Fast DDS를
사용하며 `restore_data_collection_zenoh.sh`가 기존 수집 receiver로 돌아가는 명시적
경계를 제공합니다. 이 저장소는 기존 Cyclo workspace나 container를 재생성하지 않습니다.
