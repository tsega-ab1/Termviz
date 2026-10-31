#!/usr/bin/env python3
"""TERMVIZ mini player: a slim bar docked at the top of a tmux window.

    [ spinning record ]   track name
                          previous line / CURRENT LINE / next line
                          0:42 ━━●────── 3:21          [ |< ] [ || ] [ >| ] [ portrait ]

Everything below the bar is a normal shell pane, so you can keep coding in
the same terminal while the music plays. Because it is a real tmux pane,
vim / htop / git etc. behave exactly as usual.

Keys (focus the bar with Ctrl-b then Up, or use the F-keys from anywhere):
    F7 or Space   pause / resume          F6 or p   previous / restart
    F8 or n       next track              Left/Right   seek -/+ 10 s
    q             close the bar (stops the music)

Needs: tmux, ffplay (part of ffmpeg). Not for Termux (its ffmpeg has no ffplay);
use the full-screen player there.
"""

import argparse
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import termios
import time
import traceback
import tty

import numpy as np

import dashboard
import lyrics_io
import panel
import render
from braille import braille_lines

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
BASE, EOL, RESET = panel.BASE, panel.EOL, "\x1b[0m"
BOLD, DIM, NORMAL = panel.BOLD, panel.DIM, panel.NORMAL
KEYS = (("F6", "p"), ("F7", "Space"), ("F8", "n"))      # tmux key -> key sent to the bar
DEFAULT_ROWS = 10
FPS = 12.0
SEEK = 10.0


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def vlen(s):
    return len(ANSI_RE.sub("", s))


def fit(s, width):
    """Pad (never cut) a styled string to exactly `width` visible columns."""
    return s + " " * max(0, width - vlen(s))


def clip(s, n):
    return s if len(s) <= n else s[:max(1, n - 1)] + "…"


def center(s, width):
    return " " * max(0, (width - len(s)) // 2) + s


def fmt_time(t):
    t = int(max(0, t))
    return f"{t // 60}:{t % 60:02d}"


def natural_key(name):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def build_queue(first):
    """The chosen track first, then the other audio files in its folder
    (natural order), wrapping around so 'previous' from track 1 goes to the last."""
    first = os.path.abspath(first)
    folder = os.path.dirname(first)
    try:
        names = sorted(os.listdir(folder), key=natural_key)
    except OSError:
        names = []
    tracks = [os.path.join(folder, n) for n in names
              if os.path.splitext(n)[1].lower() in dashboard.AUDIO_EXT
              and os.path.isfile(os.path.join(folder, n))]
    real = [os.path.realpath(t) for t in tracks]
    if os.path.realpath(first) not in real:
        tracks.insert(0, first)
        return tracks
    i = real.index(os.path.realpath(first))
    return tracks[i:] + tracks[:i]


# ---------------------------------------------------------------------------
# audio: ffplay + our own clock (pause = SIGSTOP, seek = restart at offset)
# ---------------------------------------------------------------------------

class Audio:
    def __init__(self):
        self.proc = None
        self.path = None
        self.base = 0.0              # track position when the clock last (re)started
        self.anchor = time.monotonic()
        self.playing = False
        self.spawned_at = 0.0
        self.failed = False

    # -- process plumbing ---------------------------------------------------
    def _kill(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.kill(self.proc.pid, signal.SIGKILL)      # works even if stopped
                self.proc.wait(timeout=1)
            except Exception:
                pass
        self.proc = None

    def _spawn(self, start):
        self._kill()
        self.spawned_at = time.monotonic()
        if self.path and shutil.which("ffplay"):
            self.proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                 "-ss", f"{start:.2f}", self.path],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)

    def _signal(self, sig):
        if self.proc and self.proc.poll() is None:
            try:
                os.kill(self.proc.pid, sig)
            except OSError:
                pass

    # -- controls -------------------------------------------------------------
    def load(self, path, start=0.0):
        self.path, self.base, self.failed = path, start, False
        self.anchor, self.playing = time.monotonic(), True
        self._spawn(start)

    def pos(self):
        return self.base + ((time.monotonic() - self.anchor) if self.playing else 0.0)

    def pause(self):
        if self.playing:
            self.base, self.playing = self.pos(), False
            self._signal(signal.SIGSTOP)

    def resume(self):
        if not self.playing:
            self.anchor, self.playing = time.monotonic(), True
            self._signal(signal.SIGCONT)

    def toggle(self):
        self.pause() if self.playing else self.resume()

    def seek(self, t):
        was_playing = self.playing
        self.base, self.anchor, self.playing = max(0.0, t), time.monotonic(), True
        self._spawn(self.base)
        if not was_playing:
            self.pause()

    def track_over(self):
        """The player process finished on its own."""
        if self.proc is None or not self.playing:
            return False
        if self.proc.poll() is None:
            return False
        if time.monotonic() - self.spawned_at < 1.5:        # died instantly = can't play it
            self.failed = True
            return False
        return True

    def stop(self):
        self._kill()
        self.playing = False


# ---------------------------------------------------------------------------
# the bar
# ---------------------------------------------------------------------------

class Dock:
    def __init__(self, args):
        self.args = args
        self.tracks = build_queue(args.music) if args.music else [None]
        self.idx = 0
        self.audio = Audio()
        self.angle = 0.0
        self.engines = {}
        self._lyrics, self._dur = {}, {}
        self.quit = False
        self.last_resize = 0.0
        self._load(0)

    # -- tracks ---------------------------------------------------------------
    def _lyrics_for(self, i):
        if i not in self._lyrics:
            path = None
            if i == 0 and self.args.lyrics:
                path = self.args.lyrics
            elif self.tracks[i]:
                path = dashboard.guess_lyrics(self.tracks[i])
            try:
                self._lyrics[i] = lyrics_io.load_lyrics(path) if path else []
            except Exception:
                self._lyrics[i] = []
        return self._lyrics[i]

    def _duration_for(self, i):
        if i not in self._dur:
            if self.tracks[i]:
                self._dur[i] = render.get_duration(self.tracks[i])
            else:                                    # silent: loop the lyric timeline
                ly = self._lyrics_for(i)
                self._dur[i] = (ly[-1]["end"] + 1.0) if ly else None
        return self._dur[i]

    def _load(self, i, start=0.0):
        self.idx = i % len(self.tracks)
        self.audio.load(self.tracks[self.idx], start)

    def next(self):
        self._load(self.idx + 1)

    def prev(self):
        if self.audio.pos() > 3.0 or len(self.tracks) == 1:
            self._load(self.idx)                     # restart this track
        else:
            self._load(self.idx - 1)

    # -- input ----------------------------------------------------------------
    def handle_keys(self):
        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0)[0]:
            data = os.read(fd, 64)
            if not data:
                break
            for tok in re.findall(rb"\x1b\[[0-9;]*[A-Za-z~]|.", data, re.S):
                if tok in (b" ", b"k"):
                    self.audio.toggle()
                elif tok in (b"n", b"N", b"."):
                    self.next()
                elif tok in (b"p", b"P", b","):
                    self.prev()
                elif tok == b"\x1b[C":
                    self.audio.seek(self.audio.pos() + SEEK)
                elif tok == b"\x1b[D":
                    self.audio.seek(self.audio.pos() - SEEK)
                elif tok in (b"q", b"Q", b"\x03"):
                    self.quit = True

    # -- drawing --------------------------------------------------------------
    def _image_lines(self, cols):
        if cols not in self.engines:
            eng = render.PortraitEngine(self.args.image, cols, render.DEFAULT_REGIONS,
                                         square=True, style=self.args.style,
                                         threshold=self.args.threshold, renderer="braille")
            self.engines[cols] = braille_lines(np.array(eng.base))
        return self.engines[cols]

    def _controls(self, width):
        playing = self.audio.playing
        btn = lambda s: f"\x1b[7m {s} \x1b[27m"
        row = f"{btn('|<')}  {btn('||' if playing else '> ')}  {btn('>|')}"
        plain = 3 * 4 + 4
        hint = "  p · space · n   ←/→ seek   q close"
        if plain + len(hint) <= width:
            row += DIM + hint + NORMAL
            plain += len(hint)
        return " " * max(0, (width - plain) // 2) + row

    def frame(self, cols, rows, dt):
        t = self.audio.pos()
        dur = self._duration_for(self.idx)
        if self.audio.playing:
            self.angle = (self.angle + dt * panel.DEG_PER_SEC) % 360.0

        if rows < 5 or cols < 30:
            msg = "bar too small - enlarge the pane"
            return "\x1b[H" + BASE + msg + EOL + RESET

        usable = cols - 1
        gap, side = 2, rows * 2
        show_img = usable >= 2 * side + 2 * gap + 26
        show_disk = usable >= side + gap + 26
        mid_w = usable - (side + gap if show_disk else 0) - (side + gap if show_img else 0)

        # middle column: title / lyrics (+progress bar) / buttons
        if self.audio.failed:
            title = "can't play this file (is ffplay installed?)"
        else:
            name = os.path.basename(self.tracks[self.idx]) if self.tracks[self.idx] else "(no music)"
            state = "" if self.audio.playing else "  [paused]"
            title = f"♪ {self.idx + 1}/{len(self.tracks)}  {name}{state}"
        mid = [DIM + center(clip(title, mid_w), mid_w) + NORMAL]
        lyr = panel.LyricsPanel(mid_w, rows - 2).rows(self._lyrics_for(self.idx), t, dur)
        mid += lyr + [""] * (rows - 2 - len(lyr))
        mid.append(self._controls(mid_w))

        disk = braille_lines(panel.draw_disk(rows * 4, self.angle)) if show_disk else None
        img = self._image_lines(side) if show_img else None

        out = []
        for r in range(rows):
            line = BASE
            if show_disk:
                line += disk[r] + " " * gap
            line += fit(mid[r], mid_w)
            if show_img:
                line += " " * gap + img[r]
            out.append(f"\x1b[{r + 1};1H{line}{EOL}{RESET}")
        return "".join(out)

    # -- main loop --------------------------------------------------------------
    def keep_height(self, lines):
        """Inside tmux, pull the pane back to the configured height if the window
        was resized (tmux otherwise rescales panes proportionally)."""
        pane = os.environ.get("TMUX_PANE")
        if pane and lines != self.args.bar_rows and time.time() - self.last_resize > 1.5:
            self.last_resize = time.time()
            subprocess.run(["tmux", "resize-pane", "-t", pane, "-y", str(self.args.bar_rows)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def advance_if_over(self):
        dur = self._duration_for(self.idx)
        over = self.audio.track_over()
        if not over and self.audio.proc is None and dur and self.audio.pos() > dur:
            over = True                              # no audio process: lyric-only clock
        if not over and dur and self.audio.pos() > dur + 3.0:
            over = True                              # safety net
        if over:
            self.next()                              # repeat-all: wraps to the first track

    def run(self):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *_: setattr(self, "quit", True))
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        last = time.time()
        try:
            while not self.quit:
                now = time.time()
                dt, last = now - last, now
                self.handle_keys()
                self.advance_if_over()
                size = shutil.get_terminal_size((80, self.args.bar_rows))
                self.keep_height(size.lines)
                sys.stdout.write(self.frame(size.columns, size.lines, dt))
                sys.stdout.flush()
                wait = max(0.0, 1.0 / FPS - (time.time() - now))
                select.select([fd], [], [], wait)
        finally:
            self.audio.stop()
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
            sys.stdout.flush()
            unbind_keys()


# ---------------------------------------------------------------------------
# tmux plumbing
# ---------------------------------------------------------------------------

def _tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def bind_keys(pane):
    for key, send in KEYS:
        _tmux("bind-key", "-n", key, "send-keys", "-t", pane, send)


def unbind_keys():
    if shutil.which("tmux") and os.environ.get("TMUX"):
        for key, _ in KEYS:
            _tmux("unbind-key", "-n", key)


def launch(sel, style="detail", threshold=128, rows=DEFAULT_ROWS):
    """Open the bar in a pane at the top of the current tmux window (or start a
    new tmux session with it). Returns (ok, message). When it starts a new
    session this call does not return: the terminal is handed over to tmux."""
    if not shutil.which("tmux"):
        return False, "tmux is not installed (sudo apt install tmux)"
    if not shutil.which("ffplay"):
        return False, "ffplay is not installed (sudo apt install ffmpeg)"

    cmd = [sys.executable, os.path.abspath(__file__), "--image", sel["image"],
           "--bar-rows", str(rows), "--style", style, "--threshold", str(threshold)]
    if sel.get("music"):
        cmd += ["--music", sel["music"]]
    if sel.get("lyrics"):
        cmd += ["--lyrics", sel["lyrics"]]
    shell_cmd = " ".join(shlex.quote(c) for c in cmd)
    split = ["split-window", "-d", "-v", "-b", "-l", str(rows), "-P", "-F", "#{pane_id}"]

    if os.environ.get("TMUX"):
        res = _tmux(*split, shell_cmd)
        if res.returncode != 0:
            return False, "tmux error: " + res.stderr.strip()
        bind_keys(res.stdout.strip())
        return True, "mini bar opened - F6/F7/F8 = prev / pause / next"

    size = shutil.get_terminal_size((100, 30))
    session = f"termviz{os.getpid()}"
    res = _tmux("new-session", "-d", "-s", session, "-c", os.getcwd(),
                "-x", str(size.columns), "-y", str(size.lines))
    if res.returncode != 0:
        return False, "tmux error: " + res.stderr.strip()
    res = _tmux(*split[:1], "-t", session, *split[1:], shell_cmd)
    if res.returncode != 0:
        return False, "tmux error: " + res.stderr.strip()
    bind_keys(res.stdout.strip())
    os.execvp("tmux", ["tmux", "attach-session", "-t", session])


# ---------------------------------------------------------------------------
# entry point (this is what runs inside the bar pane)
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="TERMVIZ mini player bar (runs in a tmux pane)")
    ap.add_argument("--image", required=True)
    ap.add_argument("--music", "--audio", dest="music")
    ap.add_argument("--lyrics")
    ap.add_argument("--bar-rows", type=int, default=DEFAULT_ROWS)
    ap.add_argument("--style", default="detail",
                    choices=["detail", "dither", "threshold", "threshold-soft"])
    ap.add_argument("--threshold", type=int, default=128)
    args = ap.parse_args()
    try:
        Dock(args).run()
    except Exception:
        traceback.print_exc()
        input("\nmini bar crashed - press Enter to close ")


if __name__ == "__main__":
    main()
