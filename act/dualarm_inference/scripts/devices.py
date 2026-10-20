#!/usr/bin/env python3
"""Register USB roles without opening a motor port or enabling torque."""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / 'config/devices.local.yaml'
CONFIG = LOCAL_CONFIG if LOCAL_CONFIG.exists() else ROOT / 'config/devices.yaml'
SERIAL_ROLES = ('left_leader', 'left_follower', 'right_leader', 'right_follower')
CAMERA_ROLES = ('top', 'wrist_left', 'wrist_right')


def bindings(config):
    return {**config['serial'], **{k: v['device'] for k, v in config['cameras'].items()}}


def check(config, roles):
    paths = bindings(config)
    errors = []
    seen = {}
    for role in roles:
        path = paths[role]
        if not path:
            errors.append(f'{role}: no USB path assigned')
            continue
        p = Path(path)
        if not p.exists():
            errors.append(f'{role}: device is not connected: {path}')
            continue
        if not stat.S_ISCHR(p.stat().st_mode):
            errors.append(f'{role}: not a character device: {path}')
        real = str(p.resolve())
        if real in seen:
            errors.append(f'{role} and {seen[real]} point to the same device: {real}')
        seen[real] = role
        if not os.access(p, os.R_OK | os.W_OK):
            errors.append(f'{role}: USB read/write permission is missing')
        if role in CAMERA_ROLES:
            result = subprocess.run(['v4l2-ctl', '-d', path, '--all'], capture_output=True, text=True)
            if result.returncode or 'Video Capture' not in result.stdout:
                errors.append(f'{role}: not a usable V4L2 capture node (check video-index0)')
    for name, camera in config['cameras'].items():
        if camera['rotation_deg'] not in (0, 90, 180, 270):
            errors.append(f'{name}: rotation must be 0, 90, 180 or 270')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    bind = commands.add_parser('bind')
    bind.add_argument('role', choices=SERIAL_ROLES + CAMERA_ROLES)
    bind.add_argument('path')
    validate = commands.add_parser('check')
    validate.add_argument('--serial-only', action='store_true')
    validate.add_argument('--cameras-only', action='store_true')
    validate.add_argument('--side', choices=('left', 'right', 'both'), default='both')
    validate.add_argument('--mode', choices=('teleop', 'inference'), default='teleop')
    validate.add_argument('--hold-other', action='store_true')
    args = parser.parse_args()
    config = yaml.safe_load(CONFIG.read_text())
    if args.command == 'list':
        for directory in ('/dev/serial/by-id', '/dev/serial/by-path', '/dev/v4l/by-id', '/dev/v4l/by-path'):
            for path in sorted(Path(directory).glob('*')):
                print(f'{path} -> {path.resolve()}')
        print('Assigned roles:')
        for role, path in bindings(config).items():
            print(f'  {role}: {path or "UNASSIGNED"}')
        return
    if args.command == 'bind':
        prefix = ('/dev/serial/by-id/', '/dev/serial/by-path/') if args.role in SERIAL_ROLES else (
            '/dev/v4l/by-id/', '/dev/v4l/by-path/')
        if not args.path.startswith(prefix):
            parser.error('Use a stable by-id or by-path device link; numbered tty/video paths are refused.')
        if args.role in SERIAL_ROLES:
            config['serial'][args.role] = args.path
        else:
            config['cameras'][args.role]['device'] = args.path
        roles = [role for role, path in bindings(config).items()
                 if path and (role == args.role or Path(path).exists())]
        errors = check(config, roles)
        if errors:
            parser.error('\n'.join(errors))
        LOCAL_CONFIG.write_text(yaml.safe_dump(config, sort_keys=False))
        print(f'Registered {args.role}: {args.path}')
        return
    roles = SERIAL_ROLES if args.serial_only else CAMERA_ROLES if args.cameras_only else SERIAL_ROLES + CAMERA_ROLES
    roles = [r for r in roles if (args.side == 'both' or r == 'top' or args.side in r)
             and (args.mode != 'inference' or not r.endswith('leader'))]
    if args.hold_other and args.side != 'both' and not args.cameras_only:
        roles.append(f'{"right" if args.side == "left" else "left"}_follower')
    errors = check(config, roles)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        sys.exit(1)
    print('USB bindings validated. No motor commands were sent.')


if __name__ == '__main__':
    main()
