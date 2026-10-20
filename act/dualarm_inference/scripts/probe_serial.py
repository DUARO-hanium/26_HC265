#!/usr/bin/env python3
"""Read-only DYNAMIXEL pings verify leaders 1..6 and followers 11..16."""
from pathlib import Path
import argparse
import sys

from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler
import yaml

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--side', choices=('left', 'right', 'both'), default='both')
parser.add_argument('--mode', choices=('teleop', 'inference'), default='teleop')
parser.add_argument('--hold-other', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
device_file = root / 'config/devices.local.yaml'
if not device_file.exists():
    device_file = root / 'config/devices.yaml'
config = yaml.safe_load(device_file.read_text())
failed = False
for role, path in config['serial'].items():
    if (args.side != 'both' and not role.startswith(args.side)
            and not (args.hold_other and role.endswith('follower'))):
        continue
    if args.mode == 'inference' and role.endswith('leader'):
        continue
    if not path:
        print(f'{role}: no port assigned', file=sys.stderr)
        failed = True
        continue
    port = PortHandler(path)
    try:
        if not port.openPort() or not port.setBaudRate(1000000):
            raise RuntimeError('Cannot open the USB port at 1 Mbps')
        packet = PacketHandler(2.0)
        ids = range(1, 7) if role.endswith('leader') else range(11, 17)
        for motor_id in ids:
            model, comm, error = packet.ping(port, motor_id)
            if comm != COMM_SUCCESS or error:
                raise RuntimeError(f'ID {motor_id}: {packet.getTxRxResult(comm)}; device error={error}')
            print(f'{role}: ID={motor_id}, model={model}')
    except Exception as exc:
        print(f'{role}: {exc}', file=sys.stderr)
        failed = True
    finally:
        port.closePort()
sys.exit(1 if failed else 0)
