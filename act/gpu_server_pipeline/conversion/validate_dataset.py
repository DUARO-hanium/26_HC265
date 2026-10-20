#!/usr/bin/env python3
"""Validate official LeRobot structure, numerical contract, and video contract."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
from torch.utils.data import DataLoader

try:
    from .convert_dataset import CAMERA_KEYS, DEFAULT_TASK, FPS, JOINTS
except ImportError:  # direct script execution
    from convert_dataset import CAMERA_KEYS, DEFAULT_TASK, FPS, JOINTS


def ffprobe(path: Path) -> dict:
    command = [
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,pix_fmt,width,height,avg_frame_rate,nb_read_frames",
        "-of", "json", str(path),
    ]
    return json.loads(subprocess.check_output(command, text=True))["streams"][0]


def validate(args: argparse.Namespace) -> dict:
    root = args.root.resolve()
    meta = LeRobotDatasetMetadata(args.repo_id, root=root)
    dataset = LeRobotDataset(args.repo_id, root=root, video_backend="torchcodec")
    if meta.total_episodes != args.expected_episodes:
        raise AssertionError((meta.total_episodes, args.expected_episodes))
    if len(dataset) != meta.total_frames:
        raise AssertionError("loader length and metadata frame count differ")
    if meta.fps != FPS:
        raise AssertionError(f"fps={meta.fps}")
    if set(meta.camera_keys) != {f"observation.images.{key}" for key in CAMERA_KEYS}:
        raise AssertionError(meta.camera_keys)
    for key in meta.camera_keys:
        feature = meta.features[key]
        if tuple(feature["shape"]) != (480, 640, 3) or feature["dtype"] != "video":
            raise AssertionError((key, feature))
    for key in ("observation.state", "action"):
        feature = meta.features[key]
        if tuple(feature["shape"]) != (6,) or feature["dtype"] != "float32":
            raise AssertionError((key, feature))
        if list(feature["names"]) != JOINTS:
            raise AssertionError((key, feature["names"]))

    episode_table = pd.read_parquet(root / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    episode_indices = episode_table["episode_index"].tolist()
    if episode_indices != list(range(args.expected_episodes)):
        raise AssertionError(f"non-contiguous episode indices: {episode_indices}")
    tasks = pd.read_parquet(root / "meta" / "tasks.parquet")
    task_values = (
        tasks["task"].astype(str).tolist()
        if "task" in tasks.columns
        else tasks.index.astype(str).tolist()
    )
    if set(task_values) != {args.expected_task}:
        raise AssertionError(tasks)

    sample_indices = sorted({0, len(dataset) // 2, len(dataset) - 1})
    samples = []
    for index in sample_indices:
        item = dataset[index]
        for key in meta.camera_keys:
            image = item[key]
            if tuple(image.shape) != (3, 480, 640) or not torch.isfinite(image).all():
                raise AssertionError((index, key, image.shape))
        for key in ("observation.state", "action"):
            value = item[key]
            if tuple(value.shape) != (6,) or value.dtype != torch.float32 or not torch.isfinite(value).all():
                raise AssertionError((index, key, value))
        samples.append(index)

    loader = DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)
    batch = next(iter(loader))
    if tuple(batch["observation.state"].shape) != (4, 6):
        raise AssertionError(batch["observation.state"].shape)
    if tuple(batch["action"].shape) != (4, 6):
        raise AssertionError(batch["action"].shape)

    probes = {}
    for key in meta.camera_keys:
        video_files = sorted((root / "videos" / key).rglob("*.mp4"))
        if not video_files:
            raise AssertionError(f"no video files for {key}")
        key_probes = []
        total_video_frames = 0
        for video in video_files:
            probe = ffprobe(video)
            if probe["codec_name"] != "h264" or probe["pix_fmt"] != "yuv420p":
                raise AssertionError((video, probe))
            if (int(probe["width"]), int(probe["height"])) != (640, 480):
                raise AssertionError((video, probe))
            if probe["avg_frame_rate"] != "30/1":
                raise AssertionError((video, probe))
            total_video_frames += int(probe["nb_read_frames"])
            key_probes.append({"path": str(video.relative_to(root)), **probe})
        if total_video_frames != len(dataset):
            raise AssertionError((key, total_video_frames, len(dataset)))
        probes[key] = {"total_frames": total_video_frames, "files": key_probes}

    stats = json.loads((root / "meta" / "stats.json").read_text(encoding="utf-8"))
    for key in ("observation.state", "action"):
        for stat_name, value in stats[key].items():
            if not np.isfinite(np.asarray(value, dtype=float)).all():
                raise AssertionError((key, stat_name, value))

    return {
        "official_loader": "pass",
        "repo_id": args.repo_id,
        "num_episodes": meta.total_episodes,
        "num_frames": len(dataset),
        "fps": meta.fps,
        "sampled_indices": samples,
        "batch_shapes": {
            "observation.state": list(batch["observation.state"].shape),
            "action": list(batch["action"].shape),
            **{key: list(batch[key].shape) for key in meta.camera_keys},
        },
        "video_probes": probes,
        "finite_stats": True,
        "task": args.expected_task,
        "joint_order": JOINTS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--expected-episodes", type=int, required=True)
    parser.add_argument("--expected-task", default=DEFAULT_TASK)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = validate(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
