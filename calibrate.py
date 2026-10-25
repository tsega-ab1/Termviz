#!/usr/bin/env python3
"""
Region calibration helper.

Renders your portrait exactly the way render.py will (same square-canvas
centering, same aspect handling), with a fractional coordinate grid
overlaid onto the photo area, so you can read off (x0, y0, x1, y1) boxes
for "forehead", "eyes", "mouth", "neck", etc.

Usage:
    python calibrate.py --image portrait.jpg --cols 90
    python calibrate.py --image portrait.jpg --cols 90 --no-square
"""

import argparse
import shutil

import numpy as np

from render import PortraitEngine, DEFAULT_REGIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--no-square", action="store_true")
    args = ap.parse_args()

    cols = args.cols or shutil.get_terminal_size((80, 40)).columns
    engine = PortraitEngine(args.image, cols, DEFAULT_REGIONS,
                             square=not args.no_square)

    arr = np.array(engine.base).astype(np.int16)
    px0, py0, px1, py1 = engine.photo_box

    # overlay grid lines every 10% of the PHOTO area (not the padded canvas)
    pw, ph = px1 - px0, py1 - py0
    for frac in [0.1 * i for i in range(1, 10)]:
        x = int(px0 + frac * pw)
        y = int(py0 + frac * ph)
        arr[:, max(0, x - 1):x + 1] = 128
        arr[max(0, y - 1):y + 1, :] = 128

    # mark the photo boundary itself so padding vs. photo is obvious
    arr[py0:py0 + 1, px0:px1] = 200
    arr[py1 - 1:py1, px0:px1] = 200
    arr[py0:py1, px0:px0 + 1] = 200
    arr[py0:py1, px1 - 1:px1] = 200

    h, w = arr.shape
    lines = []
    for y in range(0, h, 2):
        top = arr[y]
        bot = arr[y + 1] if y + 1 < h else arr[y]
        row = []
        for x in range(w):
            t, b = top[x], bot[x]
            def color(v):
                if v == 128:
                    return "255;0;0"      # grid lines: red
                if v == 200:
                    return "0;255;0"      # photo boundary: green
                if v >= 180:
                    return "255;255;255"  # white
                return "0;0;0"            # black
            row.append(f"\x1b[38;2;{color(t)};48;2;{color(b)}m▀")
        lines.append("".join(row) + "\x1b[0m")

    print("\n".join(lines))
    print()
    print("Green = boundary of the actual undistorted photo.")
    print("Red = 10% grid steps within the photo (fractions run 0.0-1.0).")
    print("Read off fractions for each face region, e.g.:")
    print('  "forehead": [0.20, 0.05, 0.80, 0.28]')
    print("Save as regions.json and pass it to render.py/launch.sh with --regions")


if __name__ == "__main__":
    main()
