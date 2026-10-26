#!/usr/bin/env python3
"""The "panel" layout: portrait on top, and under it a spinning vinyl record
on the left with the lyrics on the right.

Everything here is plain functions/classes over numpy + PIL (no terminal
access), so it can be tested without a screen. render.play() glues it to the
audio clock.

    portrait (braille)
    ----------------------------------------
    [ spinning record ]   previous line (dim)
                          CURRENT LINE (typed out)
                          next line (dim)
                          0:42 ----o------- 3:21
"""

import math
import textwrap

import numpy as np
from PIL import Image, ImageDraw

from braille import braille_lines

BASE = "\x1b[38;2;255;255;255;48;2;0;0;0m"   # white on black
EOL = "\x1b[K"                                # erase to end of line
BOLD, DIM, NORMAL = "\x1b[1m", "\x1b[2m", "\x1b[22m"

RPM = 100.0 / 3.0                 # 33 1/3 rpm
DEG_PER_SEC = RPM * 360.0 / 60.0  # = 200 degrees per second
HOLD_AFTER_END = 3.0              # keep a finished line up this long


# ---------------------------------------------------------------------------
# the record
# ---------------------------------------------------------------------------

def _pt(c, r, deg):
    a = math.radians(deg)
    return (c + r * math.cos(a), c + r * math.sin(a))


def draw_disk(size, angle, tonearm=True):
    """A vinyl record as a size x size 0/255 array. `angle` (degrees,
    clockwise) turns the label marker and the two light sweeps; the grooves
    are circular, so those moving parts are what make the spin visible."""
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    c = (size - 1) / 2.0
    R = c

    d.ellipse([0, 0, size - 1, size - 1], outline=255)               # rim
    r, inner, step = R * 0.92, R * 0.40, max(2.5, R / 7.0)
    while r > inner:                                                  # grooves
        d.ellipse([c - r, c - r, c + r, c + r], outline=255)
        r -= step

    g = R * 0.36                                                      # gap, then label
    d.ellipse([c - g, c - g, c + g, c + g], fill=0)
    lab = R * 0.30
    d.ellipse([c - lab, c - lab, c + lab, c + lab], fill=255)
    d.line([_pt(c, 0, 0), _pt(c, lab * 0.9, angle)], fill=0, width=1)  # label pointer
    mx, my = _pt(c, R * 0.17, angle + 90)
    mr = max(1.0, R * 0.06)
    d.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=0)           # label dot
    s = max(1.0, R * 0.05)
    d.ellipse([c - s, c - s, c + s, c + s], fill=0)                   # spindle hole

    arr = np.array(img)

    # two light sweeps on opposite sides, dotted so they read as a sheen
    sweep = Image.new("L", (size, size), 0)
    sd = ImageDraw.Draw(sweep)
    for off in (0, 180):
        a0 = (angle + off - 16) % 360
        a1 = (angle + off + 16) % 360
        sd.pieslice([0, 0, size - 1, size - 1], a0, a1, fill=255)
    sd.ellipse([c - g, c - g, c + g, c + g], fill=0)
    yy, xx = np.indices(arr.shape)
    arr[(np.array(sweep) > 0) & ((xx + yy) % 2 == 0)] = 255

    if tonearm:                                                       # arm from the top-right corner
        pivot = (size - 1.5, 1.0)
        tip = _pt(c, R * 0.62, -40)
        img2 = Image.fromarray(arr)
        d2 = ImageDraw.Draw(img2)
        d2.line([pivot, tip], fill=0, width=3)                        # dark edge keeps it visible
        d2.line([pivot, tip], fill=255, width=1)
        d2.ellipse([tip[0] - 2, tip[1] - 2, tip[0] + 2, tip[1] + 2], fill=0)
        d2.ellipse([tip[0] - 1, tip[1] - 1, tip[0] + 1, tip[1] + 1], fill=255)
        arr = np.array(img2)
    return arr


# ---------------------------------------------------------------------------
# layout math
# ---------------------------------------------------------------------------

def plan_layout(term_cols, term_lines, reserve=2):
    """Split the terminal between the square portrait and the bottom panel.
    `reserve` lines are left free for the shell prompt that comes back later."""
    total = max(14, term_lines - reserve)
    panel_rows = int(max(8, min(16, round(total * 0.36))))
    gap, min_text = 2, 14
    while panel_rows > 6 and panel_rows * 2 + gap + min_text > term_cols:
        panel_rows -= 1
    portrait_rows = max(6, total - panel_rows - 1)       # 1 row for the divider
    portrait_cols = max(12, min(term_cols, portrait_rows * 2))
    disk_w = panel_rows * 2
    panel_w = min(term_cols, max(portrait_cols, disk_w + gap + 22))
    return {
        "panel_rows": panel_rows,
        "portrait_cols": portrait_cols,
        "portrait_rows": portrait_cols // 2,             # square canvas -> cols/2 rows
        "disk_px": panel_rows * 4,
        "disk_w": disk_w,
        "gap": gap,
        "panel_w": panel_w,
        "text_w": max(8, panel_w - disk_w - gap),
        "portrait_left": max(0, (term_cols - portrait_cols) // 2),
        "panel_left": max(0, (term_cols - panel_w) // 2),
    }


# ---------------------------------------------------------------------------
# lyric text
# ---------------------------------------------------------------------------

def current_index(lyrics, t):
    """Index of the last line that has started by time t (or -1)."""
    idx = -1
    for i, e in enumerate(lyrics):
        if e["start"] <= t:
            idx = i
        else:
            break
    return idx


def _fmt(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class LyricsPanel:
    """Builds the right-hand text block: previous line (dim), the current
    line typed out in bold, the next line (dim) and a progress bar."""

    def __init__(self, width, height):
        self.width = width
        self.height = height

    def _wrap(self, text, limit=None):
        return textwrap.wrap(text.upper(), (limit or self.width) - 1) or [""]

    def _progress(self, t, duration):
        w = self.width
        if not duration:
            return DIM + _fmt(t).center(w) + NORMAL
        left, right = _fmt(t), _fmt(duration)
        bar_w = max(0, w - len(left) - len(right) - 2)
        if bar_w < 6:
            return DIM + f"{left} / {right}".center(w) + NORMAL
        pos = min(bar_w - 1, int(max(0.0, min(1.0, t / duration)) * (bar_w - 1)))
        bar = "━" * pos + "●" + "─" * (bar_w - pos - 1)
        return DIM + f"{left} {bar} {right}" + NORMAL

    def rows(self, lyrics, t, duration=None):
        """Exactly `height` strings (styled, at most `width` visible chars)."""
        w, h = self.width, self.height
        body_h = max(1, h - 1)                           # last row = progress bar
        idx = current_index(lyrics, t)
        cur = None
        if idx >= 0 and t <= lyrics[idx]["end"] + HOLD_AFTER_END:
            cur = lyrics[idx]
            prev = lyrics[idx - 1] if idx >= 1 else None
        else:
            prev = lyrics[idx] if idx >= 0 else None     # finished line fades back
        nxt = lyrics[idx + 1] if idx + 1 < len(lyrics) else None

        cur_lines = []
        if cur:
            full = self._wrap(cur["text"])[:max(1, body_h - 2)]
            dur = max(0.01, cur["end"] - cur["start"])
            reveal = min(max(0.2, 0.6 * dur), 1.6)
            frac = max(0.0, min(1.0, (t - cur["start"]) / reveal))
            budget = math.ceil(frac * sum(len(x) for x in full))
            typing = frac < 1.0
            cursor_placed = False
            for line in full:
                margin = max(0, (w - len(line)) // 2)    # centered on the FULL line, so
                shown = line[:budget]                    # typing doesn't shift the text
                budget = max(0, budget - len(line))
                if typing and not cursor_placed and len(shown) < len(line):
                    cursor_placed = True                 # blinking block at the typing frontier
                    if int(t * 4) % 2 == 0:
                        shown += "█"
                cur_lines.append((BOLD, " " * margin + shown))

        def dimmed(entry, take):
            if not entry:
                return []
            lines = self._wrap(entry["text"])
            lines = lines[-1:] if take == "last" else lines[:1]
            return [(DIM, " " * max(0, (w - len(x)) // 2) + x) for x in lines]

        layout = None
        for with_prev, with_next in ((True, True), (False, True), (False, False)):
            block = []
            if with_prev and prev:
                block += dimmed(prev, "last") + [("", "")]
            block += cur_lines
            if with_next and nxt:
                block += [("", "")] + dimmed(nxt, "first")
            if len(block) <= body_h:
                layout = block
                break
        if layout is None:
            layout = cur_lines[:body_h]

        top = max(0, (body_h - len(layout)) // 2)
        rows = [""] * top
        rows += [(style + text + NORMAL) if style else "" for style, text in layout]
        rows += [""] * (body_h - len(rows))
        rows.append(self._progress(t, duration))
        return rows[:h]


# ---------------------------------------------------------------------------
# putting the pieces on screen
# ---------------------------------------------------------------------------

class PanelLayout:
    def __init__(self, plan):
        self.plan = plan
        self.text = LyricsPanel(plan["text_w"], plan["panel_rows"])

    def disk_lines(self, angle):
        return braille_lines(draw_disk(self.plan["disk_px"], angle))

    def compose(self, portrait_lines, disk_lines, text_rows):
        """One full frame string, starting with cursor-home and ending with
        erase-below, so no stale characters are ever left behind."""
        p = self.plan
        out = []
        pad = " " * p["portrait_left"]
        for line in portrait_lines:
            out.append(BASE + pad + line + EOL)
        out.append(BASE + " " * p["panel_left"] + DIM + "─" * p["panel_w"] + NORMAL + EOL)
        pad = " " * p["panel_left"]
        gap = " " * p["gap"]
        for i in range(p["panel_rows"]):
            out.append(BASE + pad + disk_lines[i] + gap + text_rows[i] + NORMAL + EOL)
        return "\x1b[H" + "\n".join(out) + "\x1b[0m\x1b[J"
