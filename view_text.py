#!/usr/bin/env python3
"""
Draw ONE piece of text onto the portrait, centered, sized proportionally
to the actual image resolution (not a fixed pixel number). No regions,
no timing, no lyrics.json -- just: does text-on-image work at all, in
the same black/white style as the portrait.

Usage:
    python view_text.py --image Elvis_Presley.jpg --text "HELLO"
    python view_text.py --image Elvis_Presley.jpg --text "HELLO" --size-frac 0.25
"""

import argparse
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from render import (PortraitEngine, DEFAULT_REGIONS, render_frame,
                     ensure_terminal_size, find_font, draw_adaptive_text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--text", default="HELLO")
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--no-square", action="store_true")
    ap.add_argument("--style", default="threshold",
                     choices=["dither", "threshold", "threshold-soft"])
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--renderer", default="braille", choices=["halfblock", "braille"])
    ap.add_argument("--size-frac", type=float, default=0.15,
                     help="text height as a fraction of image width (default 0.15)")
    ap.add_argument("--skip-zoom-wait", action="store_true")
    ap.add_argument("--outline", action="store_true",
                     help="thin black outline around the letters (not a filled box) "
                          "for legibility over light areas -- text still sits directly on the face")
    ap.add_argument("--adaptive", action="store_true",
                     help="per-LETTER adaptive color: samples the blurred (noise-free) "
                          "background under each individual character and colors that "
                          "letter black or white accordingly -- one word can mix both "
                          "colors if it spans light and dark parts of the face")
    args = ap.parse_args()

    ensure_terminal_size(skip=args.skip_zoom_wait)

    term_size = shutil.get_terminal_size((80, 40))
    if args.cols:
        cols = args.cols
    else:
        cols = max(20, min(term_size.columns, (term_size.lines - 2) * 2))

    engine = PortraitEngine(args.image, cols, DEFAULT_REGIONS,
                             square=not args.no_square,
                             style=args.style, threshold=args.threshold,
                             renderer=args.renderer)

    canvas = engine.base.copy()
    draw = ImageDraw.Draw(canvas)

    # size proportional to the ACTUAL rendered resolution, not a fixed
    # pixel number -- this is the fix for text being invisible/tiny now
    # that images render at 4x the old resolution
    size = max(6, int(engine.px_w * args.size_frac))
    text = args.text.upper()

    # constrain to the actual PHOTO area, not the padded square canvas --
    # otherwise text can spill into the black letterbox bars on the sides
    px0, py0, px1, py1 = engine.photo_box
    photo_w, photo_h = px1 - px0, py1 - py0
    max_w = photo_w * 0.92

    font = find_font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    while tw > max_w and size > 6:
        size -= 1
        font = find_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    cx, cy = px0 + photo_w / 2, py0 + photo_h / 2
    pos = (cx - tw / 2, cy - th / 2)

    # text drawn directly onto the face -- no backing box behind it
    if args.adaptive:
        # blur the background first so fine dithering speckle doesn't
        # leak into the decision -- what matters is whether a given spot
        # reads as generally light or dark, not each raw dot.
        blurred = np.array(engine.base.filter(ImageFilter.GaussianBlur(radius=4)))
        draw_adaptive_text(draw, blurred, text, pos, font)
    elif args.outline:
        # thin black stroke around the letters only (not a filled box) --
        # keeps text sitting directly on the face while staying legible
        # over light areas too
        for dx, dy in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            draw.text((pos[0]+dx, pos[1]+dy), text, font=font, fill=0)
        draw.text(pos, text, font=font, fill=255)
    else:
        draw.text(pos, text, font=font, fill=255)

    arr = np.array(canvas).astype(np.int16)
    ansi = render_frame(arr, renderer=args.renderer)
    sys.stdout.write(ansi + "\n")
    sys.stdout.flush()

    print(f"[diagnostic] image {engine.px_w}x{engine.px_h}px, "
          f"text '{text}' at font size {size}px ({args.size_frac*100:.0f}% of width), "
          f"bbox {int(tw)}x{int(th)}px")


if __name__ == "__main__":
    main()
