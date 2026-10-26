#!/usr/bin/env python3
"""Load a lyric timing file into the flat list render.py plays.

Accepted inputs:
  * flat JSON list:      [{"start": 1.0, "end": 3.5, "text": "..."}, ...]
  * whisper-style JSON:  {"segments": [{"start": .., "end": .., "text": ".."}, ...]}
  * LRC:                 [mm:ss.xx]text   (one or more timestamps per line)

Whatever the input, the result is a list of dicts sorted by start time with
sane start/end values: {"start", "end", "text", "effect"}.
"""

import json
import os
import re

MIN_DURATION = 0.4
SECONDS_PER_WORD = 0.35
LRC_TAG = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def _from_json(data):
    if isinstance(data, dict):
        data = data.get("segments") or data.get("lyrics") or data.get("lines")
    if not isinstance(data, list):
        raise ValueError("unrecognized lyrics JSON (need a list, or a 'segments' list)")
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        start = item.get("start", item.get("time"))
        if not text or start is None:
            continue
        end = item.get("end")
        out.append({
            "start": float(start),
            "end": float(end) if end is not None else None,
            "text": text,
            "effect": item.get("effect", "hold"),
        })
    return out


def _from_lrc(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            tags = LRC_TAG.findall(line)
            if not tags:
                continue  # metadata like [ar:...] or blank lines
            text = LRC_TAG.sub("", line).strip()
            if not text:
                continue
            for mm, ss in tags:
                out.append({"start": int(mm) * 60 + float(ss), "end": None,
                            "text": text, "effect": "hold"})
    return out


def _fix_timing(entries):
    """Fill in missing ends and repair zero-length ones (common in
    auto-transcribed files where word timing collapsed)."""
    entries.sort(key=lambda e: e["start"])
    for i, e in enumerate(entries):
        nxt = entries[i + 1]["start"] if i + 1 < len(entries) else None
        words = max(1, len(e["text"].split()))
        estimate = e["start"] + max(MIN_DURATION, words * SECONDS_PER_WORD)
        end = e["end"]
        if end is None:
            # LRC style: the line lasts until the next one starts
            end = min(nxt, e["start"] + 8.0) if nxt is not None else e["start"] + 4.0
        elif end <= e["start"]:
            end = estimate if nxt is None else min(estimate, nxt - 0.05)
        e["end"] = max(end, e["start"] + 0.2)
    return entries


def load_lyrics(path):
    """Return the normalized, sorted lyric list for any supported file."""
    if os.path.splitext(path)[1].lower() == ".lrc":
        entries = _from_lrc(path)
    else:
        with open(path, encoding="utf-8") as f:
            entries = _from_json(json.load(f))
    return _fix_timing(entries)
