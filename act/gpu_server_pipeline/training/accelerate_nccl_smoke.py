"""Minimal official Accelerate collective test for the configured GPU count."""

import os

import torch
import torch.distributed as dist
from accelerate import Accelerator


accelerator = Accelerator()
rank = accelerator.process_index
device = accelerator.device
value = torch.tensor(float(rank + 1), device=device)

if dist.is_initialized():
    dist.all_reduce(value, op=dist.ReduceOp.SUM)

expected = accelerator.num_processes * (accelerator.num_processes + 1) / 2
print(
    f"rank={rank} local_rank={accelerator.local_process_index} "
    f"device={device} gpu={torch.cuda.get_device_name(device)} "
    f"reduced={value.item()} expected={expected} "
    f"visible={os.environ.get('CUDA_VISIBLE_DEVICES')}",
    flush=True,
)
accelerator.wait_for_everyone()

if value.item() != expected:
    raise RuntimeError(f"Expected all-reduced value {expected}, got {value.item()}")
