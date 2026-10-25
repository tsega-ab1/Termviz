#!/usr/bin/env python3
"""
Convert a whisper/forced-alignment style lyrics JSON (segments -> words,
each with start/end) into the flat format render.py expects.

Handles messy/zeroed timestamps by falling back to a per-word duration
estimate when a segment's own start/end look broken (start >= end, or
end == 0 while start > 0).

Usage:
    python convert_lyrics.py --in Elvis_Presley.json --out lyrics.json
"""

import argparse
import json

REGIONS_CYCLE = ["forehead", "eyes", "mouth", "neck"]
EFFECTS_CYCLE = ["typewriter", "hold", "fade", "glitch"]

WORD_DURATION_FALLBACK = 0.35  # seconds/word, used when timestamps are broken
MIN_DURATION = 0.4


def fix_segment_timing(seg, next_start):
    start = seg.get("start", 0) or 0
    end = seg.get("end", 0) or 0
    n_words = max(1, len(seg.get("text", "").split()))

    broken = (end <= start)
    if broken:
        est = start + max(MIN_DURATION, n_words * WORD_DURATION_FALLBACK)
        if next_start is not None and next_start > start:
            end = min(est, next_start - 0.05)
        else:
            end = est
        end = max(end, start + MIN_DURATION)

    return start, end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--out", dest="outfile", required=True)
    args = ap.parse_args()

    with open(args.infile) as f:
        data = json.load(f)

    segments = data.get("segments", [])
    segments = [s for s in segments if s.get("text", "").strip()]
    segments.sort(key=lambda s: s.get("start", 0))

    out = []
    for i, seg in enumerate(segments):
        next_start = segments[i + 1]["start"] if i + 1 < len(segments) else None
        start, end = fix_segment_timing(seg, next_start)

        # avoid zero/negative-length gaps overlapping the previous entry
        if out and start < out[-1]["end"]:
            start = out[-1]["end"] + 0.02
            if end <= start:
                end = start + MIN_DURATION

        region = REGIONS_CYCLE[i % len(REGIONS_CYCLE)]
        effect = EFFECTS_CYCLE[i % len(EFFECTS_CYCLE)]

        out.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "text": seg["text"].strip(),
            "region": region,
            "effect": effect,
            "size": 18,
        })

    with open(args.outfile, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {len(out)} lyric entries to {args.outfile}")
    print("Spot-check a few timestamps against the actual song before running.")


if __name__ == "__main__":
    main()
