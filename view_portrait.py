#!/usr/bin/env python3
"""
Render the portrait ONCE as a static frame and exit. No lyrics, no
animation loop, no alt-screen buffer, no audio. This isolates the core
image-to-ANSI rendering path so it can be verified on its own, separate
from anything timing- or lyrics-related.

The output stays on screen after the script exits (normal scrollback,
not the alternate screen buffer), so you can screenshot it directly.

Usage:
    python view_portrait.py --image Elvis_Presley.jpg
    python view_portrait.py --image Elvis_Presley.jpg --cols 50
    python view_portrait.py --image Elvis_Presley.jpg --no-square
"""

import argparse
import shutil
import sys

import numpy as np

from render import PortraitEngine, DEFAULT_REGIONS, render_frame, apply_scanlines, ensure_terminal_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--no-square", action="store_true")
    ap.add_argument("--no-scanlines", action="store_true",
                     help="skip the scanline effect, pure dithered image only")
    ap.add_argument("--style", default="threshold",
                     choices=["dither", "threshold", "threshold-soft"])
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--renderer", default="braille", choices=["halfblock", "braille"],
                     help="braille = 4x pixel density (default)")
    ap.add_argument("--skip-zoom-wait", action="store_true")
    args = ap.parse_args()

    ensure_terminal_size(skip=args.skip_zoom_wait)

    term_size = shutil.get_terminal_size((80, 40))
    if args.cols:
        cols = args.cols
    else:
        cols = max(20, min(term_size.columns, (term_size.lines - 2) * 2))

    print(f"[diagnostic] terminal reports: {term_size.columns} cols x "
          f"{term_size.lines} lines -> using square canvas of {cols} chars "
          f"(style={args.style}, renderer={args.renderer})")

    engine = PortraitEngine(args.image, cols, DEFAULT_REGIONS,
                             square=not args.no_square,
                             style=args.style, threshold=args.threshold,
                             renderer=args.renderer)

    arr = np.array(engine.base).astype(np.int16)
    if not args.no_scanlines:
        arr = apply_scanlines(arr)
    arr = np.clip(arr, 0, 255)

    ansi = render_frame(arr, renderer=args.renderer)
    sys.stdout.write(ansi + "\n")
    sys.stdout.flush()

    print(f"[diagnostic] rendered {engine.px_w}x{engine.px_h} px "
          f"({engine.rows} terminal lines) -- photo_box={engine.photo_box}")


if __name__ == "__main__":
    main()
