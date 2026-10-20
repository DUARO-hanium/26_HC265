#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Subset

from lerobot.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.factory import make_policy


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an official LeRobot ACT forward/backward smoke test"
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=10)
    args = parser.parse_args()
    root = args.root.resolve()
    chunk_size = args.chunk_size
    metadata = LeRobotDatasetMetadata(args.repo_id, root=root)
    delta_timestamps = {
        "action": [i / metadata.fps for i in range(chunk_size)]
    }
    dataset = LeRobotDataset(
        args.repo_id, root=root, delta_timestamps=delta_timestamps
    )
    # A reduced transformer is sufficient for an interface/loss smoke test while
    # retaining the official ACTPolicy implementation and both real camera inputs.
    config = ACTConfig(
        device="cpu",
        push_to_hub=False,
        chunk_size=chunk_size,
        n_action_steps=chunk_size,
        pretrained_backbone_weights=None,
        dim_model=64,
        n_heads=4,
        dim_feedforward=128,
        n_encoder_layers=1,
        n_decoder_layers=1,
        latent_dim=8,
        n_vae_encoder_layers=1,
    )
    policy = make_policy(config, ds_meta=metadata)
    policy.train()

    # Include an interior sample and an episode-end sample to exercise padding.
    episodes = metadata.episodes
    end_index = int(episodes[0]["dataset_to_index"]) - 1
    indices = [100, end_index]
    batch = next(iter(DataLoader(Subset(dataset, indices), batch_size=2, shuffle=False)))
    loss, loss_dict = policy(batch)
    loss.backward()

    grad_finite = all(
        torch.isfinite(parameter.grad).all().item()
        for parameter in policy.parameters()
        if parameter.grad is not None
    )
    result = {
        "status": "pass" if math.isfinite(loss.item()) and grad_finite else "fail",
        "official_policy_class": type(policy).__name__,
        "lerobot_version": __import__("lerobot").__version__,
        "indices": indices,
        "chunk_size": chunk_size,
        "action_shape": list(batch["action"].shape),
        "action_is_pad_shape": list(batch["action_is_pad"].shape),
        "episode_end_padded_steps": int(batch["action_is_pad"][1].sum().item()),
        "camera1_shape": list(batch["observation.images.camera1"].shape),
        "camera2_shape": list(batch["observation.images.camera2"].shape),
        "state_shape": list(batch["observation.state"].shape),
        "loss": float(loss.item()),
        "loss_components": loss_dict,
        "loss_finite": math.isfinite(loss.item()),
        "gradients_finite": grad_finite,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
