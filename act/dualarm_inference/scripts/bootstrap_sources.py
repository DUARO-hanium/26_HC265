#!/usr/bin/env python3
"""Restore pinned official sources and apply the workspace's small Cyclo patch."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(directory, *arguments, check=True, quiet=False):
    return subprocess.run(['git', '-C', str(directory), *arguments], check=check,
                          stdout=subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None)


def main():
    manifest = json.loads((ROOT / 'config/source_manifest.json').read_text())
    for name in ('open_manipulator', 'cyclo_intelligence'):
        source = manifest[name]
        directory = ROOT / name
        if not directory.exists():
            subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout', source['url'], str(directory)], check=True)
            git(directory, 'checkout', '--detach', source['commit'])
        head = subprocess.check_output(['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()
        if head != source['commit']:
            raise RuntimeError(f'{name}: expected {source["commit"]}, found {head}; '
                               'existing checkouts are never reset automatically')
        submodules = source.get('submodules', [])
        if submodules:
            git(directory, 'submodule', 'update', '--init', '--recursive', '--depth', '1', '--', *submodules)
        if source.get('patch'):
            patch = str(ROOT / source['patch'])
            applied = git(directory, 'apply', '--reverse', '--check', patch, check=False, quiet=True)
            if applied.returncode:
                git(directory, 'apply', '--check', patch)
                git(directory, 'apply', patch)
        print(f'{name}: pinned source and workspace patch ready', flush=True)

    for relative in ('runtime/control-agent', 'runtime/cyclo-agent',
                     'checkpoints/left/pretrained_model', 'checkpoints/right/pretrained_model',
                     'checkpoints/left_open_success/pretrained_model',
                     'classifier_images/train/open', 'classifier_images/train/not_open',
                     'classifier_images/validation/open', 'classifier_images/validation/not_open'):
        (ROOT / relative).mkdir(parents=True, exist_ok=True)
    (ROOT / 'cyclo_intelligence/docker/workspace/rosbag2').mkdir(parents=True, exist_ok=True)
    datasets = ROOT / 'datasets'
    if not datasets.exists() and not datasets.is_symlink():
        datasets.symlink_to('cyclo_intelligence/docker/workspace/rosbag2')


if __name__ == '__main__':
    main()
