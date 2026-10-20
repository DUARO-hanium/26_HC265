# Remote ACT inference runbook

## GPU server

서버에도 이 저장소를 clone하고 `server/server.env`를 준비합니다. `CHECKPOINT_PATH`와
로컬 `.env`의 `REMOTE_CHECKPOINT`는 서버에서 보이는 동일한 `pretrained_model`
디렉터리여야 합니다.

```bash
cp server/server.env.example server/server.env
chmod 600 server/server.env
editor server/server.env
./server/setup_server_env.sh
./server/run_policy_server.sh 0 58080
```

GPU 번호는 매 실행 시 선택합니다. PolicyServer는 loopback에만 bind되므로 학교 VPN에
접속했더라도 포트를 외부에 공개하지 않습니다.

## WSL tunnel과 local graph

`.env`의 `SSH_TARGET`을 `~/.ssh/config` alias 또는 `user@host`로 설정합니다.

```bash
./scripts/open_ssh_tunnel.sh
./scripts/start_existing_container.sh
./scripts/switch_camera_receivers_to_fastdds.sh
```

구조는 `WSL container -> host.docker.internal:58080 -> WSL 127.0.0.1:58080 -> SSH ->
server 127.0.0.1:58080`입니다. ROS 2 graph는 노트북 내부 Fast DDS이고, 영상/관절은
LeRobot async-inference gRPC로 전달됩니다. 인터넷 단절이나 VPN 만료 시 client는
과거 action을 계속 재생하지 않습니다.

## Dry-run과 실제 구동

Follower bringup 터미널은 계속 켜 둡니다.

```bash
./scripts/run_follower_only.sh
```

새 터미널:

```bash
./scripts/run_container_preflight.sh --duration 30 --min-rate 25 \
  --warn-dxl-gap 0.12 --max-dxl-gap 0.50 --max-dxl-loss-fraction 0.20
./scripts/move_to_profile_pose.sh commissioning_start_pose.interior.json
DRY_RUN=true MAX_EXECUTED_ACTIONS=60 ./scripts/run_container_client.sh
```

Dry-run topic은 `/remote_inference/dry_run_joint_trajectory`이며 controller 명령 topic과
분리됩니다. 결과가 타당할 때만 실제 mode를 사용합니다.

```bash
unset MAX_EXECUTED_ACTIONS
DRY_RUN=false ARM_REAL_HARDWARE=I_UNDERSTAND_THIS_MOVES_OMX \
  ./scripts/run_container_client.sh
```

`MAX_EXECUTED_ACTIONS`가 unset이면 task execution time 제한은 없습니다. 작업이 끝나거나
이상 동작이 보이면 client 터미널에서 `Ctrl+C`를 누릅니다.
