#!/usr/bin/env python3
"""TERMVIZ: dashboard -> player -> back to the dashboard.

    python termviz.py                      # open the dashboard
    python termviz.py --image me.jpg --music song.m4a --lyrics song.lrc
    python termviz.py --image me.jpg --play   # skip the dashboard, play now

Flags only pre-fill the dashboard (unless --play), so you can still change
anything before pressing Play.
"""

import argparse
import os

import dashboard
import render


def _existing(path):
    if not path:
        return None
    path = os.path.abspath(os.path.expanduser(path))
    return path if os.path.isfile(path) else None


def main():
    ap = argparse.ArgumentParser(description="Retro terminal portrait + lyrics player")
    ap.add_argument("--image", help="portrait to show")
    ap.add_argument("--music", "--audio", dest="music", help="music file (optional)")
    ap.add_argument("--lyrics", help="lyrics file, .json or .lrc (optional)")
    ap.add_argument("--play", action="store_true",
                     help="skip the dashboard and play right away (needs an image)")
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--no-square", action="store_true")
    ap.add_argument("--style", default="threshold",
                     choices=["dither", "threshold", "threshold-soft"])
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--renderer", default="braille", choices=["halfblock", "braille"])
    ap.add_argument("--audio-delay", type=float, default=0.0)
    ap.add_argument("--skip-zoom-wait", action="store_true")
    args = ap.parse_args()

    sel = dashboard.load_config()
    for key, flag in (("image", args.image), ("music", args.music), ("lyrics", args.lyrics)):
        if flag:
            found = _existing(flag)
            if not found:
                raise SystemExit(f"{key}: file not found: {flag}")
            sel[key] = found

    play_opts = dict(cols=args.cols, fps=args.fps, square=not args.no_square,
                     style=args.style, threshold=args.threshold,
                     renderer=args.renderer, audio_delay=args.audio_delay,
                     skip_zoom_wait=args.skip_zoom_wait)

    first = True
    while True:
        if args.play and first:
            if not sel["image"]:
                raise SystemExit("--play needs an image (--image or a saved choice)")
            chosen = sel
        else:
            chosen = dashboard.run(sel)
        first = False
        if chosen is None:
            break
        try:
            render.play(chosen["image"], lyrics_path=chosen["lyrics"],
                        audio=chosen["music"], **play_opts)
        except KeyboardInterrupt:
            pass
        if args.play:
            break
        sel = chosen


if __name__ == "__main__":
    main()
