#!/usr/bin/env python3
"""Terminal dashboard: choose the portrait, the music and (optionally) the
lyrics, see a small preview, then press Play. Your last choices are
remembered in ~/.termviz.json.

Plain input()/print() on purpose -- no curses -- so it behaves the same in
Termux, over SSH and in any terminal.
"""

import json
import os
import re
import shutil
import sys
import time

import lyrics_io

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus"}
LYRICS_EXT = {".json", ".lrc"}
KIND_EXT = {"image": IMAGE_EXT, "music": AUDIO_EXT, "lyrics": LYRICS_EXT}
KIND_LABEL = {"image": "IMAGE", "music": "MUSIC", "lyrics": "LYRICS"}
CONFIG_PATH = os.path.expanduser("~/.termviz.json")
MAX_FOUND = 300

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ---------------------------------------------------------------------------
# tiny ANSI helpers
# ---------------------------------------------------------------------------

def bold(s):
    return f"\x1b[1m{s}\x1b[22m"


def dim(s):
    return f"\x1b[2m{s}\x1b[22m"


def rev(s):
    return f"\x1b[7m{s}\x1b[27m"


def vlen(s):
    return len(ANSI_RE.sub("", s))


def pad(s, width):
    return s + " " * max(0, width - vlen(s))


def clip(s, n):
    return s if len(s) <= n else s[:max(1, n - 1)] + "…"


def fmt_time(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def age(path):
    try:
        secs = max(0, time.time() - os.path.getmtime(path))
    except OSError:
        return "?"
    for limit, unit, div in ((60, "s", 1), (3600, "m", 60), (86400, "h", 3600),
                              (604800, "d", 86400)):
        if secs < limit:
            return f"{int(secs // div)}{unit} ago"
    return f"{int(secs // 604800)}w ago"


# ---------------------------------------------------------------------------
# config (remember last choices)
# ---------------------------------------------------------------------------

def load_config():
    sel = {"image": None, "music": None, "lyrics": None}
    try:
        with open(CONFIG_PATH) as f:
            saved = json.load(f)
        for key in sel:
            p = saved.get(key)
            if p and os.path.isfile(p):
                sel[key] = p
    except (OSError, ValueError):
        pass
    return sel


def save_config(sel):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump({k: sel.get(k) for k in ("image", "music", "lyrics")}, f)
    except OSError:
        pass  # remembering choices is a nicety, never fatal


# ---------------------------------------------------------------------------
# finding files
# ---------------------------------------------------------------------------

def search_dirs():
    home = os.path.expanduser("~")
    names = ("Download", "Downloads", "Music", "DCIM", "Pictures", "Documents", "Movies")
    cands = [os.getcwd(), home]
    cands += [os.path.join(home, "storage", "shared", n) for n in names]
    cands += [os.path.join(home, "storage", n.lower() + ("s" if n == "Download" else ""))
              for n in names]
    cands += [os.path.join(home, n) for n in names]
    seen, out = set(), []
    for d in cands:
        real = os.path.realpath(d)
        if real not in seen and os.path.isdir(real):
            seen.add(real)
            out.append(real)
    return out


def _listdir(d):
    try:
        return sorted(os.listdir(d))
    except OSError:
        return []


_lyrics_ok_cache = {}


def looks_like_lyrics(path):
    """True if lyrics_io can read at least one timed line from the file."""
    try:
        key = (path, os.path.getmtime(path))
        if key not in _lyrics_ok_cache:
            ok = os.path.getsize(path) < 2_000_000 and len(lyrics_io.load_lyrics(path)) > 0
            _lyrics_ok_cache[key] = ok
        return _lyrics_ok_cache[key]
    except Exception:
        return False


def scan(kind):
    """Files of this kind in the usual places (one folder level deep),
    newest first."""
    exts = KIND_EXT[kind]
    seen, found = set(), []

    def consider(p):
        if len(found) >= MAX_FOUND:
            return
        if os.path.splitext(p)[1].lower() not in exts or not os.path.isfile(p):
            return
        real = os.path.realpath(p)
        if real in seen:
            return
        if kind == "lyrics" and not looks_like_lyrics(p):
            return
        seen.add(real)
        found.append(p)

    for d in search_dirs():
        for name in _listdir(d):
            if name.startswith("."):
                continue
            p = os.path.join(d, name)
            if os.path.isdir(p):
                for sub in _listdir(p):
                    if not sub.startswith("."):
                        consider(os.path.join(p, sub))
            else:
                consider(p)

    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def guess_lyrics(music_path):
    """A lyrics file named like the music file (song.m4a -> song.lrc/.json)."""
    stem = os.path.splitext(os.path.basename(music_path))[0]
    for d in (os.path.dirname(music_path), os.getcwd()):
        for ext in (".lrc", ".json"):
            p = os.path.join(d, stem + ext)
            if os.path.isfile(p) and looks_like_lyrics(p):
                return p
    return None


# ---------------------------------------------------------------------------
# info shown on the dashboard (cached)
# ---------------------------------------------------------------------------

_duration_cache, _count_cache, _thumb_cache = {}, {}, {}


def music_length(path):
    if path not in _duration_cache:
        try:
            import render
            _duration_cache[path] = render.get_duration(path)
        except Exception:
            _duration_cache[path] = None
    return _duration_cache[path]


def lyrics_count(path):
    if path not in _count_cache:
        try:
            _count_cache[path] = len(lyrics_io.load_lyrics(path))
        except Exception:
            _count_cache[path] = 0
    return _count_cache[path]


THUMB_COLS, THUMB_ROWS = 20, 10


def thumb_lines(path):
    """Small braille preview of the chosen image, or None if it can't load."""
    if path not in _thumb_cache:
        try:
            import numpy as np
            import render
            eng = render.PortraitEngine(path, THUMB_COLS, render.DEFAULT_REGIONS,
                                         square=True, style="dither", renderer="braille")
            _thumb_cache[path] = render.braille_lines(np.array(eng.base))
        except Exception:
            _thumb_cache[path] = None
    return _thumb_cache[path]


def placeholder_thumb(text):
    rows = [" " * THUMB_COLS for _ in range(THUMB_ROWS)]
    rows[0] = "╭" + "─" * (THUMB_COLS - 2) + "╮"
    rows[-1] = "╰" + "─" * (THUMB_COLS - 2) + "╯"
    for i in range(1, THUMB_ROWS - 1):
        rows[i] = "│" + " " * (THUMB_COLS - 2) + "│"
    mid = THUMB_ROWS // 2
    rows[mid] = "│" + text.center(THUMB_COLS - 2) + "│"
    return [dim(r) for r in rows]


# ---------------------------------------------------------------------------
# screens
# ---------------------------------------------------------------------------

def clear():
    sys.stdout.write("\x1b[2J\x1b[H")


def draw(sel, msg=""):
    cols = shutil.get_terminal_size((80, 24)).columns
    show_thumb = cols >= 72
    inner = 44 if show_thumb else max(24, min(cols - 4, 52))
    val_w = inner - 12

    def value(text, ok):
        return clip(text, val_w) if ok else dim("(" + text + ")")

    if sel["image"]:
        image_v = value(os.path.basename(sel["image"]), True)
    else:
        image_v = value("none - required", False)
    if sel["music"]:
        length = music_length(sel["music"])
        extra = f"  {fmt_time(length)}" if length else ""
        music_v = clip(os.path.basename(sel["music"]), val_w - len(extra)) + dim(extra)
    else:
        music_v = value("none - optional", False)
    if sel["lyrics"]:
        n = lyrics_count(sel["lyrics"])
        lyrics_v = clip(f"{n} lines · {os.path.basename(sel['lyrics'])}", val_w)
    else:
        lyrics_v = value("none - optional", False)

    rows = [
        bold("TERMVIZ") + dim("  portrait + lyrics player"),
        "",
        f"{rev(' 1 ')} Image   {image_v}",
        f"{rev(' 2 ')} Music   {music_v}",
        f"{rev(' 3 ')} Lyrics  {lyrics_v}",
        "",
        f"{rev(' 4 ')} Play     {rev(' q ')} Quit",
        "",
        dim("type a key, then Enter"),
    ]
    box = ["╭" + "─" * (inner + 2) + "╮"]
    box += ["│ " + pad(r, inner) + " │" for r in rows]
    box += ["╰" + "─" * (inner + 2) + "╯"]

    if show_thumb:
        thumb = thumb_lines(sel["image"]) if sel["image"] else None
        if thumb is None:
            thumb = placeholder_thumb("no image" if not sel["image"] else "no preview")
        thumb = [pad(t, THUMB_COLS) for t in thumb]
        side = [" " * THUMB_COLS] + thumb          # top-align with the box interior
        side += [" " * THUMB_COLS] * max(0, len(box) - len(side))
        box = [pad(b, inner + 4) + "  " + s for b, s in zip(box, side)]

    clear()
    print("\n".join(box))
    if msg:
        print("\n" + bold(msg))
    print()


def where(path):
    return dim(f"{clip(os.path.basename(os.path.dirname(path)) or '/', 14)} · {age(path)}")


def pick(kind, current):
    """List matching files and let the user choose one, or type a path.
    Returns the chosen path (or `current` if cancelled)."""
    items = scan(kind)
    per, page, note = 8, 0, ""
    pages = max(1, (len(items) + per - 1) // per)
    while True:
        clear()
        print(bold(f"Choose {KIND_LABEL[kind]}") + dim(f"   {len(items)} found"))
        print()
        shown = items[page * per:(page + 1) * per]
        for i, p in enumerate(shown, 1):
            print(f" {rev(f' {i} ')} {clip(os.path.basename(p), 32):<32} {where(p)}")
        if not shown:
            print(dim("  nothing found in Download / Music / Pictures / DCIM / this folder"))
        print()
        hints = ["number = choose", "or paste/type a file path"]
        if pages > 1:
            hints.append(f"> next · < previous (page {page + 1}/{pages})")
        if kind == "lyrics":
            hints.append("0 = no lyrics")
        hints.append("Enter = keep current")
        print(dim("  " + "  ·  ".join(hints)))
        if note:
            print("\n" + bold(note))
        try:
            s = input("pick> ").strip()
        except (EOFError, KeyboardInterrupt):
            return current
        note = ""
        if s == "":
            return current
        if s == "0" and kind == "lyrics":
            return None
        if s == ">":
            page = min(page + 1, pages - 1)
            continue
        if s == "<":
            page = max(page - 1, 0)
            continue
        if s.isdigit():
            n = int(s)
            if 1 <= n <= len(shown):
                return shown[n - 1]
            note = f"No item {n} on this page."
            continue
        path = os.path.abspath(os.path.expanduser(s.strip("'\"")))
        if not os.path.isfile(path):
            note = "File not found: " + clip(path, 50)
        elif os.path.splitext(path)[1].lower() not in KIND_EXT[kind]:
            note = "That doesn't look like a " + kind + " file (" + \
                   ", ".join(sorted(KIND_EXT[kind])) + ")."
        elif kind == "lyrics" and not looks_like_lyrics(path):
            note = "Couldn't read timed lyrics from that file."
        else:
            return path


def run(sel=None):
    """Show the dashboard until the user presses Play (returns the chosen
    paths as a dict) or quits (returns None)."""
    sel = dict(sel) if sel else load_config()
    for key in ("image", "music", "lyrics"):
        sel.setdefault(key, None)
    msg = ""
    while True:
        draw(sel, msg)
        msg = ""
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if choice in ("q", "quit", "exit"):
            print("bye")
            return None
        if choice == "1":
            sel["image"] = pick("image", sel["image"])
        elif choice == "2":
            new = pick("music", sel["music"])
            if new and new != sel["music"]:
                sel["music"] = new
                match = guess_lyrics(new)
                if match:
                    sel["lyrics"] = match
                    msg = "Found matching lyrics: " + os.path.basename(match)
        elif choice == "3":
            sel["lyrics"] = pick("lyrics", sel["lyrics"])
        elif choice in ("4", "p", "play"):
            if not sel["image"]:
                msg = "Pick an image first (press 1)."
                continue
            save_config(sel)
            return dict(sel)
        elif choice:
            msg = f"Unknown choice: {choice!r}"


if __name__ == "__main__":
    print(run())
