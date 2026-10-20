#!/usr/bin/env python3
"""Derive a recording-only CPU image from ROBOTIS's official AMD64 Dockerfile."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
repo = root / 'cyclo_intelligence'
source = (repo / 'docker/Dockerfile.amd64').read_text()
original = 'FROM robotis/ros:jazzy-ros-base-torch2.7.0-cuda12.8.0 AS runtime'
assert source.count(original) == 1, 'Official Dockerfile changed; inspect the CPU adaptation first.'
replacement = '''FROM robotis/open-manipulator:5.1.3 AS runtime

# Workspace adaptation: data collection/conversion without CUDA.
RUN apt-get update && apt-get install -y python3-venv && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH=/opt/venv/bin:${PATH}
RUN pip install --no-cache-dir torch==2.7.0 torchvision==0.22.0 \\
    --index-url https://download.pytorch.org/whl/cpu
'''
derived = source.replace(original, replacement)
# Refresh repositories already present in the reused base image.
derived = derived.replace('RUN git clone -b jazzy https://github.com/ROBOTIS-GIT/robotis_interfaces.git',
                          'RUN rm -rf ${COLCON_WS}/src/robotis_interfaces && '
                          'git clone -b jazzy https://github.com/ROBOTIS-GIT/robotis_interfaces.git')
derived = derived.replace('RUN git clone -b main https://github.com/ROBOTIS-GIT/cyclo_manager.git',
                          'RUN rm -rf /opt/cyclo_manager && '
                          'git clone -b main https://github.com/ROBOTIS-GIT/cyclo_manager.git')
derived = derived.replace(
    '--from-paths src src/cyclo_intelligence/cyclo_data/recorder/rosbag_recorder',
    '--from-paths src/cyclo_intelligence/orchestrator src/cyclo_intelligence/cyclo_data '
    'src/cyclo_intelligence/cyclo_data/recorder/rosbag_recorder '
    'src/cyclo_intelligence/interfaces src/cyclo_intelligence/shared src/robotis_interfaces')
(repo / 'docker/Dockerfile.cpu.local').write_text(derived)
ignore = repo / '.dockerignore'
if not ignore.exists():
    ignore.write_text('.git\ncyclo_brain\ndocker/workspace\ndocker/huggingface\n'
                      '**/__pycache__\n**/*.egg-info\n**/node_modules\n')
print('CPU Dockerfile generated from the official AMD64 Dockerfile; UI and data packages unchanged.')
