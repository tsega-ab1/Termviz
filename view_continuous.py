#!/usr/bin/env python3
"""
Continuous text-on-portrait animation, decoupled entirely from audio.
Loops through lyrics.json on its own internal clock, repeating from the
start once it reaches the end. Use this to judge animation smoothness
and text rendering quality on their own, with no audio-sync variables
in the mix at all.

Usage:
    python view_continuous.py --image Elvis_Presley.jpg --lyrics lyrics.json
    python view_continuous.py --image Elvis_Presley.jpg --lyrics lyrics.json --fps 15
    python view_continuous.py --image Elvis_Presley.jpg --lyrics lyrics.json --no-loop
"""

import argparse
import shutil
import sys
import time

import numpy as np

from render import (PortraitEngine, DEFAULT_REGIONS, render_frame,
                     ensure_terminal_size, load_lyrics, draw_lyric,
                     apply_scanlines, apply_flicker, apply_glitch_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--lyrics", required=True)
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--no-square", action="store_true")
    ap.add_argument("--style", default="threshold",
                     choices=["dither", "threshold", "threshold-soft"])
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--renderer", default="braille", choices=["halfblock", "braille"])
    ap.add_argument("--no-loop", action="store_true",
                     help="play through once and stop instead of repeating")
    ap.add_argument("--no-effects", action="store_true",
                     help="skip scanline/flicker/glitch frame effects, pure text+portrait only")
    ap.add_argument("--skip-zoom-wait", action="store_true")
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
    lyrics = load_lyrics(args.lyrics)
    if not lyrics:
        print("[error] no lyric entries loaded -- check --lyrics path/content")
        return

    loop_duration = lyrics[-1]["end"] + 1.0  # +1s pause before repeating
    print(f"[diagnostic] {len(lyrics)} entries loaded, loop duration {loop_duration:.1f}s, "
          f"loop={'off' if args.no_loop else 'on'}")
    time.sleep(1)

    frame_interval = 1.0 / args.fps
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
    sys.stdout.flush()

    t0 = time.time()
    try:
        while True:
            frame_start = time.time()
            elapsed = frame_start - t0

            if elapsed > loop_duration:
                if args.no_loop:
                    break
                t0 = frame_start
                elapsed = 0.0

            canvas = engine.base.copy()
            active = [e for e in lyrics if e["start"] <= elapsed <= e["end"]]
            for entry in active:
                draw_lyric(canvas, engine, entry, elapsed)

            arr = np.array(canvas).astype(np.int16)
            if not args.no_effects:
                arr = apply_scanlines(arr)
                arr = apply_flicker(arr)
                arr = apply_glitch_rows(arr)
            arr = np.clip(arr, 0, 255)

            ansi = render_frame(arr, renderer=args.renderer)
            sys.stdout.write("\x1b[H" + ansi)
            sys.stdout.flush()

            render_time = time.time() - frame_start
            time.sleep(max(0.0, frame_interval - render_time))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
