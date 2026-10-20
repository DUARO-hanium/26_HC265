import argparse

import cv2


def main():
    parser = argparse.ArgumentParser(description='Generate the calibrated ChArUco target')
    parser.add_argument('--output', default='charuco_7x5.png')
    parser.add_argument('--squares-x', type=int, default=7)
    parser.add_argument('--squares-y', type=int, default=5)
    parser.add_argument('--square-mm', type=float, default=24.0)
    parser.add_argument('--marker-mm', type=float, default=17.28)
    parser.add_argument('--pixels-per-square', type=int, default=300)
    args = parser.parse_args()
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
    board = cv2.aruco.CharucoBoard_create(
        args.squares_x, args.squares_y, args.square_mm, args.marker_mm, dictionary)
    size = (args.squares_x * args.pixels_per_square,
            args.squares_y * args.pixels_per_square)
    image = board.draw(size, marginSize=0, borderBits=1)
    if not cv2.imwrite(args.output, image):
        raise RuntimeError(f'failed to write {args.output}')
    print(f'Wrote {args.output}')
    print(f'Print at exactly {args.squares_x * args.square_mm:.1f} x '
          f'{args.squares_y * args.square_mm:.1f} mm (100% scale; no fit-to-page)')
    print('Measure several printed squares before calibration.')
