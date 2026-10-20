# Portable LeRobot 0.6 ACT training

This directory reproduces the successful two-GPU ACT training setup without
embedding a username, server path, dataset owner, GPU number, API key, dataset,
or checkpoint. It deliberately launches the official `lerobot-train` entry
point through Hugging Face Accelerate; it does not replace the LeRobot trainer.

## 1. Configure

```bash
cd training
cp training.env.example training.env
chmod 600 training.env
editor training.env
```

Set at least `WORK_ROOT`, `VENV_DIR`, `DATASET_ROOT`, `DATASET_REPO_ID`,
`OUTPUT_DIR`, and `GPU_IDS`. `training.env` is a local Bash configuration file
and must not be committed. The scripts source this file as Bash, so only use a
configuration you created or reviewed yourself; do not source an untrusted file.

For the proven two-GPU profile, keep:

```text
NUM_PROCESSES=2
BATCH_SIZE_PER_GPU=4
MIXED_PRECISION=bf16
```

This gives global batch size 8. LeRobot does not automatically rescale the
learning rate or training steps when GPU count changes.

## 2. Install the official package

Use Python 3.12 on Linux with a working NVIDIA driver:

```bash
./scripts/setup_training_env.sh
```

The requirement is `lerobot[training]==0.6.0`; its official training extra
installs the matching dataset, Accelerate, and W&B dependencies. If your CUDA
platform needs a particular PyTorch wheel, install that wheel in the venv first
and then rerun the setup script.

## 3. Verify both GPUs and NCCL

```bash
nvidia-smi
./scripts/run_nccl_smoke.sh
```

Every rank must report a distinct local CUDA device and the same successful
all-reduce result. Do this before a long training run.

## 4. Train independently of SSH

```bash
./scripts/start_training_tmux.sh
tmux attach -t lerobot_act
```

The `train` window runs official Accelerate DDP. The `gpu-monitor` window logs
temperature, utilization, memory, and power. Temperature thresholds only write
warnings; they do not impose a custom training stop.

Detach with `Ctrl-b d`. An SSH or laptop disconnect does not stop tmux on the
GPU server.

To run in the foreground instead:

```bash
./scripts/train_act_ddp.sh
```

Metrics go to W&B only when `WANDB_ENABLE=true`. Inject `WANDB_API_KEY` from a
secret manager/session, or configure a chmod-600 key file outside the clone.
Checkpoints remain local because W&B artifact upload is disabled.

## 5. Resume

After an interruption, use the same config, visible GPUs, process count, and
per-GPU batch size:

```bash
./scripts/resume_act_ddp.sh
```

The script selects the numerically latest official checkpoint and calls
`lerobot-train --config_path=... --resume=true`. It ignores the convenience
`last` symlink/directory so numeric ordering is unambiguous.

## Default training profile

- ACT policy, CUDA
- 100,000 optimizer steps, seed 1000
- episode-level evaluation split 0.10
- full held-out evaluation every 2,500 steps
- checkpoint every 2,500 steps
- W&B checkpoint artifacts disabled

At roughly 620 MB per full checkpoint, 40 checkpoints can require about 25 GB.
Adjust `SAVE_FREQ` only after accounting for available storage.

## Dataset integrity

Copying a dataset or downloading it from Hugging Face does not transcode video;
file bytes and visual quality are unchanged. For a private Hub dataset, log in
with a read-only token and preferably set an immutable `DATASET_REVISION`.
Keep a dataset-specific SHA-256 manifest next to your private data or release
metadata, not in this generic repository.

## Tests

```bash
./tests/test_training_scripts.sh
```

The test checks Bash/Python syntax and renders the dry command to verify that
the official two-process ACT/DDP flags are preserved without leaking secrets.
