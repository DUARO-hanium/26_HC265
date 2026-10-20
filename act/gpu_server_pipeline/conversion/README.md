# Cyclo OMX recordings to LeRobot v3

This directory contains the portable, offline conversion and verification
tools used for the two-camera OMX ACT dataset. The converter performs only the
source adaptation needed for the recorded Cyclo layout. Final dataset writing
is delegated to the public `LeRobotDataset.create`, `add_frame`,
`save_episode`, and `finalize` API from LeRobot 0.6.0.

Nothing here publishes a ROS topic or writes to robot hardware. Source MCAP,
MP4, and timestamp parquet files are opened read-only. The output dataset must
not already exist, preventing accidental replacement of a converted dataset.

## Input layout

For every selected episode the default layout is:

```text
RAW_ROOT/
└── Task_0805_in_package_socks_00_MCAP/0/
    ├── 0_0.mcap
    └── videos/0_0/
        ├── camera1.mp4
        ├── camera1_timestamps.parquet
        ├── camera2.mp4
        └── camera2_timestamps.parquet
```

Use `--episode-dir-template` when the task name differs. It is a path relative
to `--source-root`; `{episode:02d}` is replaced by the episode number.

The OMX contract is fixed intentionally:

- 30 Hz output grid
- `camera1` and `camera2`, each 640×480 RGB
- state from `/joint_states`
- action from `/leader/joint_trajectory`
- ordered joints: `joint1` through `joint5`, then `gripper_joint_1`

## Environment

Use an isolated Python 3.12 environment. The versions exercised by this
project are listed in `requirements.txt`. FFmpeg/ffprobe must also be present.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r conversion/requirements.txt
```

If the shell previously sourced ROS, unset its Python/workspace overlays for
the conversion command:

```bash
unset PYTHONPATH AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH
```

## Convert

Keep the original recording and all reports outside the Git checkout:

```bash
python conversion/convert_dataset.py \
  --source-root /data/raw/in_package_socks \
  --output-root /data/lerobot/in_package_socks_v3 \
  --audit-root /data/audits/in_package_socks \
  --repo-id YOUR_HF_USER/in_package_socks \
  --episodes 0-40 \
  --task 'Pick a sock from the container and place it on the table' \
  --normalized-task-episodes 0-3
```

The conversion repairs short non-monotonic timestamp pairs without separating
timestamps from values. State/action interpolation is linear only between real
bracketing samples with a gap of at most 100 ms. Camera selection uses the
nearest real frame within 50 ms. Longer gaps are dropped and counted in the
audit; they are not hidden by extrapolation.

Videos are encoded through the LeRobot API as H.264/yuv420p, 640×480, 30 fps,
CRF 18. The converter never resizes its 640×480 source frames.

## Verify

Validate schema, finite tensors/statistics, official loading, batching, video
codec, resolution, frame rate, and frame count:

```bash
python conversion/validate_dataset.py \
  --root /data/lerobot/in_package_socks_v3 \
  --repo-id YOUR_HF_USER/in_package_socks \
  --expected-episodes 41 \
  --expected-task 'Pick a sock from the container and place it on the table' \
  --report /data/audits/in_package_socks/validation.json
```

Run an official ACT forward/backward interface smoke test:

```bash
python conversion/act_smoke_test.py \
  --root /data/lerobot/in_package_socks_v3 \
  --repo-id YOUR_HF_USER/in_package_socks \
  --report /data/audits/in_package_socks/act_smoke.json
```

Compare selected mapped raw frames with frames decoded by the official loader:

```bash
python conversion/compare_video_quality.py \
  --dataset-root /data/lerobot/in_package_socks_v3 \
  --raw-root /data/raw/in_package_socks \
  --audit-root /data/audits/in_package_socks \
  --repo-id YOUR_HF_USER/in_package_socks \
  --episodes 0,1,5,10,22,31,40
```

`--episodes` here selects converted output episode indices. The corresponding
source episode number is read from each immutable frame-mapping filename, so a
subset or reordered conversion is compared with the correct raw recording.

Unit tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q conversion/tests
```

## Provenance and exclusions

These files are sanitized from the conversion implementation used locally on
2026-08-05. Portability changes only replaced personal absolute paths and
task/layout constants with explicit CLI arguments. No dataset, video, MCAP,
audit receipt, model checkpoint, runtime log, credential, or personal path is
included.

The separate experimental `cyclo_intelligence/tools` scripts for EEPROM-bound
label clipping, checkpoint comparison, ROS replay planning, and preview safety
audits are deliberately excluded. They were investigation-specific and are not
required to reproduce the successful raw-to-LeRobot conversion. Including
them in the default path could incorrectly suggest that counterfactual label
clipping was part of the final training dataset; it was not.
