#!/usr/bin/env python3
"""
Draw a placeholder label into EVERY defined region, all at once, as a
single static frame. No animation, no timing, no lyrics.json needed.
This isolates the draw_lyric()/region_box() text-compositing logic from
the animation loop, so region placement and text sizing can be checked
on their own.

Usage:
    python view_regions.py --image Elvis_Presley.jpg --regions regions.json
"""

import argparse
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw

from render import PortraitEngine, DEFAULT_REGIONS, frame_to_ansi, find_font


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--regions", default=None)
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--no-square", action="store_true")
    args = ap.parse_args()

    term_size = shutil.get_terminal_size((80, 40))
    if args.cols:
        cols = args.cols
    else:
        cols = max(20, min(term_size.columns, (term_size.lines - 2) * 2))

    regions = DEFAULT_REGIONS
    if args.regions:
        import json
        with open(args.regions) as f:
            regions = json.load(f)

    engine = PortraitEngine(args.image, cols, regions, square=not args.no_square)
    canvas = engine.base.copy()
    draw = ImageDraw.Draw(canvas)

    for name in regions:
        if name == "full":
            continue  # skip -- it overlaps everything, would clutter the check
        x0, y0, x1, y1 = engine.region_box(name)
        w, h = x1 - x0, y1 - y0

        # outline the region box itself in mid-gray so you can see its
        # extent even where there's no text
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=140)

        size = max(8, h)
        font = find_font(size)
        label = name.upper()
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cx, cy = x0 + w / 2, y0 + h / 2
        pos = (cx - tw / 2, cy - th / 2)
        draw.rectangle([pos[0] - 2, pos[1] - 1, pos[0] + tw + 2, pos[1] + th + 2],
                       fill=0)
        draw.text(pos, label, font=font, fill=255)

    arr = np.array(canvas).astype(np.int16)
    ansi = frame_to_ansi(arr)
    sys.stdout.write(ansi + "\n")
    sys.stdout.flush()

    print("[diagnostic] gray outline = region boundary, white text = region label")
    print("Regions checked:", ", ".join(n for n in regions if n != "full"))


if __name__ == "__main__":
    main()
