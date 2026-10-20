#!/usr/bin/env python3
import argparse
import glob
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from lerobot.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata


def read_raw_frame(path: Path, frame_index: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(path))
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, bgr = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"Could not decode frame {frame_index} from {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return float("inf") if mse == 0 else 10 * math.log10((255.0**2) / mse)


def add_label(image: Image.Image, label: str) -> Image.Image:
    canvas = Image.new("RGB", (image.width, image.height + 24), "white")
    canvas.paste(image, (0, 24))
    ImageDraw.Draw(canvas).text((4, 4), label, fill="black")
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare mapped raw frames with official LeRobot decoding"
    )
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument(
        "--episodes", default="0,1,5,10,22,31,40",
        help="Comma-separated output/source episode indices to sample",
    )
    parser.add_argument(
        "--episode-dir-template",
        default="Task_0805_in_package_socks_{episode:02d}_MCAP/0",
    )
    args = parser.parse_args()
    dataset_root = args.dataset_root.resolve()
    raw_root = args.raw_root.resolve()
    audit_root = args.audit_root.resolve()
    report = audit_root / "video_quality_comparison.json"
    visual_dir = audit_root / "visual_samples"
    visual_dir.mkdir(parents=True, exist_ok=True)
    dataset = LeRobotDataset(args.repo_id, root=dataset_root)
    metadata = LeRobotDatasetMetadata(args.repo_id, root=dataset_root)
    episode_rows = {int(row["episode_index"]): row for row in metadata.episodes}
    selected_episodes = [int(value) for value in args.episodes.split(",") if value.strip()]
    records = []
    montage_rows = {"camera1": [], "camera2": []}

    for episode in selected_episodes:
        mapping_path = glob.glob(str(audit_root / "frame_mappings" / f"episode_{episode:06d}_source_*.parquet"))
        if len(mapping_path) != 1:
            raise RuntimeError(f"Expected one mapping for episode {episode}, got {mapping_path}")
        mapping_file = Path(mapping_path[0])
        match = re.fullmatch(
            r"episode_\d{6}_source_(\d+)\.parquet", mapping_file.name
        )
        if match is None:
            raise RuntimeError(f"Unexpected mapping filename: {mapping_file.name}")
        source_episode = int(match.group(1))
        mapping = pd.read_parquet(mapping_file)
        episode_row = episode_rows[episode]
        base = int(episode_row["dataset_from_index"])
        local_indices = sorted({0, len(mapping) // 2, len(mapping) - 1})

        for camera in ("camera1", "camera2"):
            tiles = []
            episode_root = Path(
                args.episode_dir_template.format(episode=source_episode)
            )
            if episode_root.is_absolute() or ".." in episode_root.parts:
                raise ValueError("episode template must stay below raw root")
            raw_video = raw_root / episode_root / "videos" / "0_0" / f"{camera}.mp4"
            for local_index in local_indices:
                source_index = int(mapping.iloc[local_index][f"{camera}_source_frame_index"])
                raw = read_raw_frame(raw_video, source_index)
                converted_tensor = dataset[base + local_index][f"observation.images.{camera}"]
                converted = (
                    converted_tensor.detach().cpu().permute(1, 2, 0).numpy().clip(0, 1) * 255
                ).round().astype(np.uint8)
                score = psnr(raw, converted)
                mae = float(np.mean(np.abs(raw.astype(np.float32) - converted.astype(np.float32))))
                records.append(
                    {
                        "episode": episode,
                        "source_episode": source_episode,
                        "camera": camera,
                        "output_local_frame": local_index,
                        "output_global_frame": base + local_index,
                        "source_frame": source_index,
                        "psnr_db": score,
                        "mean_absolute_error_8bit": mae,
                    }
                )
                raw_tile = add_label(Image.fromarray(raw).resize((320, 240)), f"raw e{episode:02d} f{source_index}")
                out_tile = add_label(Image.fromarray(converted).resize((320, 240)), f"output local {local_index}")
                tiles.extend([raw_tile, out_tile])
            row = Image.new("RGB", (sum(tile.width for tile in tiles), max(tile.height for tile in tiles)), "white")
            x = 0
            for tile in tiles:
                row.paste(tile, (x, 0))
                x += tile.width
            montage_rows[camera].append(row)

    for camera, rows in montage_rows.items():
        montage = Image.new("RGB", (max(row.width for row in rows), sum(row.height for row in rows)), "white")
        y = 0
        for row in rows:
            montage.paste(row, (0, y))
            y += row.height
        montage.save(visual_dir / f"raw_vs_lerobot_{camera}.jpg", quality=95)

    finite_psnr = [record["psnr_db"] for record in records if math.isfinite(record["psnr_db"])]
    result = {
        "status": "pass",
        "method": "Mapped source frame decoded from original MP4 compared pixelwise with the official LeRobot loader output",
        "samples": len(records),
        "episodes": selected_episodes,
        "camera_sample_counts": {
            camera: sum(record["camera"] == camera for record in records) for camera in ("camera1", "camera2")
        },
        "psnr_db_min": min(finite_psnr),
        "psnr_db_mean": float(np.mean(finite_psnr)),
        "mae_8bit_max": max(record["mean_absolute_error_8bit"] for record in records),
        "mae_8bit_mean": float(np.mean([record["mean_absolute_error_8bit"] for record in records])),
        "resolution": [640, 480],
        "montages": [
            str(Path("visual_samples") / "raw_vs_lerobot_camera1.jpg"),
            str(Path("visual_samples") / "raw_vs_lerobot_camera2.jpg"),
        ],
        "records": records,
    }
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
