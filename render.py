#!/usr/bin/env python3
"""
Retro monochrome terminal music visualizer.

Renders a portrait as pure black/white half-block ANSI art in the terminal,
composites timed lyrics directly onto the face as kinetic typography, and
layers CRT-style effects (scanlines, flicker, glitch, typewriter reveal).

Usage:
    python render.py --image portrait.jpg --lyrics lyrics.json \
                      --audio song.mp3 --cols 90 --fps 12

Run calibrate.py first to pick fractional (x, y) coordinates for regions
like "forehead", "eyes", "mouth", "neck" that match YOUR photo.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from braille import braille_lines  # noqa: F401  (also used by dashboard.py)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Terminal character cells are ~2x taller than wide. We render two vertical
# pixels per character using the unicode upper-half-block "▀" (foreground =
# top pixel, background = bottom pixel), which doubles our effective vertical
# resolution and keeps the portrait from looking squashed.
FONT_ASPECT = 0.5  # width/height ratio of a terminal cell, roughly

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

DEFAULT_REGIONS = {
    # fractional (x0, y0, x1, y1) boxes, tune with calibrate.py
    "forehead": (0.20, 0.05, 0.80, 0.28),
    "eyes":     (0.15, 0.30, 0.85, 0.42),
    "mouth":    (0.30, 0.62, 0.70, 0.75),
    "neck":     (0.25, 0.80, 0.75, 0.98),
    "full":     (0.05, 0.05, 0.95, 0.95),
}


def find_font(size):
    """Best-effort monospace/bold font lookup; falls back to PIL default."""
    candidates = [
        "/system/fonts/DroidSansMono.ttf",
        "/system/fonts/RobotoMono-Regular.ttf",
        "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
        "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def ensure_terminal_size(min_lines=35, min_cols=70, skip=False):
    """Termux's font size can't be set from a script -- it's a pinch-zoom
    gesture stored internally by the terminal app, no config file or
    command controls it. The practical equivalent: pause here, tell the
    person to zoom out, and actively re-check terminal size every half
    second until it's big enough (or they press Enter to proceed anyway
    at the current size)."""
    if skip:
        return

    size = shutil.get_terminal_size((80, 40))
    if size.columns >= min_cols and size.lines >= min_lines:
        return  # already big enough, nothing to do

    print(f"[setup] Terminal is {size.columns}x{size.lines} chars -- "
          f"pinch-zoom OUT for a denser render (target: {min_cols}x{min_lines}+).")
    print("[setup] Waiting for a bigger terminal... "
          "(press Enter at any time to continue at the current size)")

    import select
    while True:
        size = shutil.get_terminal_size((80, 40))
        if size.columns >= min_cols and size.lines >= min_lines:
            print(f"[setup] Got {size.columns}x{size.lines} -- continuing.")
            time.sleep(0.3)  # let the resize settle
            return
        # non-blocking check for Enter keypress so the wait can be skipped
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        if ready:
            sys.stdin.readline()
            print(f"[setup] Continuing at {size.columns}x{size.lines}.")
            return


# ---------------------------------------------------------------------------
# Image engine
# ---------------------------------------------------------------------------

def bw_convert(img, style="threshold", threshold=128, contrast_boost=True):
    """Convert a grayscale PIL image to pure black/white using one of:
      - "dither": Floyd-Steinberg error-diffusion (speckled, simulates
        gray tones via scattered pixels)
      - "threshold": hard cutoff, every pixel goes fully black or white
        (solid, connected regions -- stencil/silkscreen look, no speckle)
      - "threshold-soft": threshold with a slight blur first, to smooth
        jagged edges from noise while still producing solid regions
    """
    from PIL import ImageOps, ImageFilter

    if contrast_boost:
        img = ImageOps.autocontrast(img, cutoff=1)

    if style == "dither":
        return img.convert("1", dither=Image.FLOYDSTEINBERG).convert("L")

    if style == "threshold-soft":
        img = img.filter(ImageFilter.GaussianBlur(radius=1))

    # plain threshold (also used by threshold-soft after blurring)
    return img.point(lambda p: 255 if p >= threshold else 0)


class PortraitEngine:
    def __init__(self, image_path, cols, regions, square=True,
                 style="threshold", threshold=128, renderer="halfblock"):
        self.cols = cols
        self.regions = regions
        self.renderer = renderer
        # Sub-pixels per character cell: half-block gives 2 (top/bottom),
        # braille gives 8 (a 2x4 dot grid) -> 4x the pixel density in the
        # same terminal footprint. This is what "cols" pixels-per-char
        # multiplier applies below.
        px_per_char_w = 2 if renderer == "braille" else 1
        px_per_char_h = 4 if renderer == "braille" else 2

        src = Image.open(image_path).convert("L")
        w, h = src.size

        if square:
            # A square CHARACTER grid (cols wide, cols/2 tall, since a
            # terminal cell is ~1:2 width:height) maps to a square PIXEL
            # canvas once each dimension is scaled by its own sub-pixel
            # count: (cols * px_per_char_w) == (cols/2 * px_per_char_h)
            # for both halfblock (1,2) and braille (2,4). So canvas_px is
            # just cols * px_per_char_w in both cases.
            canvas_px = cols * px_per_char_w
            scale = min(canvas_px / w, canvas_px / h)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            resized = src.resize((new_w, new_h), Image.LANCZOS)
            resized = bw_convert(resized, style=style, threshold=threshold)

            canvas = Image.new("L", (canvas_px, canvas_px), 0)  # black backdrop
            offset = ((canvas_px - new_w) // 2, (canvas_px - new_h) // 2)
            canvas.paste(resized, offset)

            self.base = canvas
            self.px_w = self.px_h = canvas_px
            self.rows = canvas_px // px_per_char_h
            # remember where the actual (undistorted) photo sits inside the
            # square canvas, so regions can be defined relative to the FACE,
            # not the padded canvas
            self.photo_box = (offset[0], offset[1], offset[0] + new_w, offset[1] + new_h)
        else:
            # BUG FIX: this previously had an extra "* 2" here, which doubled
            # the vertical scale and stretched every portrait tall.
            rows = max(10, int(cols * (h / w) * FONT_ASPECT))
            self.rows = rows
            px_w, px_h = cols * px_per_char_w, rows * px_per_char_h

            img = src.resize((px_w, px_h), Image.LANCZOS)
            img = bw_convert(img, style=style, threshold=threshold)

            self.base = img
            self.px_w, self.px_h = px_w, px_h
            self.photo_box = (0, 0, px_w, px_h)

    def region_box(self, name):
        """Fractional (x0,y0,x1,y1) box, mapped onto the actual photo area
        (self.photo_box) so regions still track the face correctly even
        when the photo is letterboxed inside a square canvas."""
        x0, y0, x1, y1 = self.regions.get(name, self.regions["full"])
        px0, py0, px1, py1 = self.photo_box
        pw, ph = px1 - px0, py1 - py0
        return (
            int(px0 + x0 * pw), int(py0 + y0 * ph),
            int(px0 + x1 * pw), int(py0 + y1 * ph),
        )


# ---------------------------------------------------------------------------
# Lyrics
# ---------------------------------------------------------------------------

def load_lyrics(path):
    """Load timed lyrics from flat JSON, whisper-style JSON or .lrc
    (see lyrics_io.py for the accepted formats)."""
    from lyrics_io import load_lyrics as _load
    return _load(path)


def bayer_mask(shape, density):
    """4x4 ordered-dither mask; density in [0,1] = fraction of pixels kept."""
    bayer4 = np.array([
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ]) / 16.0
    tiled = np.tile(bayer4, (shape[0] // 4 + 1, shape[1] // 4 + 1))
    tiled = tiled[:shape[0], :shape[1]]
    return tiled < density


def draw_adaptive_text(draw, blurred_arr, text, pos, font):
    """Per-letter adaptive black/white text: walks the string character by
    character, samples the blurred (dither-noise-smoothed) background under
    EACH letter, and colors that letter black or white for contrast. A thin
    outline in the opposite color is added per letter too, since even a
    correctly-chosen solid color can still land on same-colored speckle in
    a textured/dithered area and vanish -- the outline guarantees a visible
    edge regardless. One word can end up mixing both colors if it spans
    both light and dark parts of the portrait.
    """
    bbox = draw.textbbox((0, 0), text, font=font)
    th = bbox[3] - bbox[1]
    h, w = blurred_arr.shape
    x_cursor = pos[0]
    for ch in text:
        ch_w = draw.textlength(ch, font=font)
        cx0, cy0 = int(x_cursor), int(pos[1])
        cx1, cy1 = int(x_cursor + max(ch_w, 1)), int(pos[1] + th)
        cx0, cy0 = max(0, cx0), max(0, cy0)
        cx1 = min(w, max(cx1, cx0 + 1))
        cy1 = min(h, max(cy1, cy0 + 1))

        region = blurred_arr[cy0:cy1, cx0:cx1]
        avg_brightness = region.mean() if region.size else 128
        ch_color = 0 if avg_brightness >= 128 else 255
        outline_color = 255 - ch_color

        for dx, dy in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            draw.text((x_cursor + dx, pos[1] + dy), ch, font=font, fill=outline_color)
        draw.text((x_cursor, pos[1]), ch, font=font, fill=ch_color)
        x_cursor += ch_w


def draw_lyric(canvas_img, engine, entry, t, size_frac=0.22):
    """Composite one active lyric entry onto canvas_img (PIL 'L' image) at
    time t. Always centered directly on the actual photo, always the same
    fixed size, always solid black -- no per-line shrink-to-fit, no
    positional jitter, no adaptive per-letter coloring. Simple and
    consistent across every lyric line."""
    text = entry["text"].upper()
    dur = max(0.01, entry["end"] - entry["start"])
    progress = min(1.0, max(0.0, (t - entry["start"]) / dur))
    effect = entry.get("effect", "hold")

    if effect == "typewriter":
        n_chars = max(1, int(progress * len(text)))
        text = text[:n_chars]

    draw = ImageDraw.Draw(canvas_img)

    px0, py0, px1, py1 = engine.photo_box
    photo_w, photo_h = px1 - px0, py1 - py0

    # fixed size for every line, no auto-shrink -- a long line may run
    # past the photo edges rather than get a different size than a short one
    size = max(10, int(photo_w * size_frac))
    font = find_font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # fixed center position for every line, always -- no jitter
    cx, cy = px0 + photo_w / 2, py0 + photo_h / 2
    pos = (cx - tw / 2, cy - th / 2)

    if effect == "fade":
        # simulate opacity in pure monochrome via ordered dithering --
        # reveals solid BLACK pixels progressively (inverted from the old
        # white-reveal version)
        density = progress if progress < 1.0 else 1.0
        text_layer = Image.new("L", canvas_img.size, 0)
        ImageDraw.Draw(text_layer).text(pos, text, font=font, fill=255)
        arr = np.array(text_layer) > 0
        keep = bayer_mask(arr.shape, density)
        arr = arr & keep
        base_arr = np.array(canvas_img)
        base_arr[arr] = 0
        canvas_img.paste(Image.fromarray(base_arr))
        return

    # plain solid black text, same for hold/typewriter/glitch
    draw.text(pos, text, font=font, fill=0)


# ---------------------------------------------------------------------------
# Effects (whole-frame, per animation tick)
# ---------------------------------------------------------------------------

def apply_scanlines(arr):
    arr[::2, :] = (arr[::2, :] * 0.55).astype(arr.dtype)
    return arr


def apply_flicker(arr, strength=0.06):
    if random.random() < strength:
        factor = random.uniform(0.75, 0.95)
        arr = (arr * factor).astype(arr.dtype)
    return arr


def apply_glitch_rows(arr, chance=0.04):
    if random.random() < chance:
        h = arr.shape[0]
        band = random.randint(1, 3)
        y = random.randint(0, h - band - 1)
        shift = random.randint(-6, 6)
        arr[y:y + band, :] = np.roll(arr[y:y + band, :], shift, axis=1)
    return arr


# ---------------------------------------------------------------------------
# ANSI rendering with run-length encoding (keeps it fast enough for a phone)
# ---------------------------------------------------------------------------

def frame_to_ansi(bw_arr):
    """bw_arr: 2D array of 0/255, even height. Returns one ANSI string."""
    h, w = bw_arr.shape
    lines = []
    for y in range(0, h, 2):
        top = bw_arr[y]
        bot = bw_arr[y + 1] if y + 1 < h else bw_arr[y]
        row_chunks = []
        last_pair = None
        run = []

        def flush():
            if run:
                row_chunks.append("".join(run))

        for x in range(w):
            pair = (top[x] >= 128, bot[x] >= 128)
            if pair != last_pair:
                fg = "38;2;255;255;255" if pair[0] else "38;2;0;0;0"
                bg = "48;2;255;255;255" if pair[1] else "48;2;0;0;0"
                run.append(f"\x1b[{fg};{bg}m▀")
                last_pair = pair
            else:
                run.append("▀")
        flush()
        lines.append("".join(row_chunks) + "\x1b[0m")
    return "\n".join(lines)


# Bit weights for each dot position within a braille cell's 2-wide x
# 4-tall dot grid, per the Unicode braille pattern encoding (dots
# 1,2,3,7 down the left column; 4,5,6,8 down the right column).
_BRAILLE_BITS = [
    [0x01, 0x08],
    [0x02, 0x10],
    [0x04, 0x20],
    [0x40, 0x80],
]


def frame_to_braille_ansi(bw_arr):
    """Whole frame as one ANSI string: a single white-on-black color escape
    (braille already encodes the black/white pattern) plus the glyph rows."""
    return ("\x1b[38;2;255;255;255;48;2;0;0;0m"
            + "\n".join(braille_lines(bw_arr)) + "\x1b[0m")


def render_frame(bw_arr, renderer="halfblock"):
    if renderer == "braille":
        return frame_to_braille_ansi(bw_arr)
    return frame_to_ansi(bw_arr)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def get_duration(audio_path):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ])
        return float(out.strip())
    except Exception:
        return None


class _NullProc:
    """Stand-in so callers can always call .terminate()/.wait() safely."""
    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass


class _TermuxMediaPlayerProc(_NullProc):
    """termux-media-player runs async via Android's service, not a child
    process we hold a handle to, so terminate() has to issue a stop command."""
    def terminate(self):
        subprocess.run(["termux-media-player", "stop"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_audio(audio_path):
    """Returns (proc, measured_start_time). measured_start_time is the
    wall-clock time.time() at which audio actually started playing, used
    by the caller as the true t0 for lyric timing -- this replaces
    guessing a fixed --audio-delay with an actual measurement.
    """
    # Prefer ffplay if present (simplest, handles most formats/backends,
    # and its Popen call itself has much lower/more predictable startup
    # latency than going through Android's MediaPlayer service).
    if shutil.which("ffplay"):
        proc = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path]
        )
        return proc, time.time()

    # Termux's ffmpeg build often omits ffplay (needs SDL2). The standard
    # Termux way to play audio directly is termux-media-player, which uses
    # Android's native audio system (requires the Termux:API app + package).
    # Its "play" command returns as soon as the request is HANDED OFF to
    # Android's background media service -- actual playback can start a
    # variable amount of time later (codec init, service wake-up, etc).
    # Rather than guess that delay, poll "termux-media-player info" right
    # after issuing play, and record the wall-clock moment it actually
    # reports playback underway.
    if shutil.which("termux-media-player"):
        subprocess.run(["termux-media-player", "play", audio_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc = _TermuxMediaPlayerProc()

        poll_timeout = 5.0
        poll_interval = 0.05
        deadline = time.time() + poll_timeout
        while time.time() < deadline:
            try:
                out = subprocess.check_output(
                    ["termux-media-player", "info"],
                    stderr=subprocess.DEVNULL, timeout=1.0
                )
                info = json.loads(out.decode())
                playing = info.get("playing")
                position = info.get("currentPosition") or info.get("position") or 0
                if playing or (isinstance(position, (int, float)) and position > 0):
                    print(f"[diagnostic] audio start detected after "
                          f"{poll_timeout - (deadline - time.time()):.2f}s poll")
                    return proc, time.time()
            except Exception:
                pass  # info command failed/unsupported this round, keep polling
            time.sleep(poll_interval)

        # Fell through without detecting a start -- don't hang, just warn
        # and fall back to "assume it started now", same as before.
        print("[diagnostic] could not confirm audio start via 'termux-media-player "
              "info' (unsupported or timed out) -- falling back to assumed start "
              "time. Use --audio-delay to compensate if lyrics run ahead of audio.")
        return proc, time.time()

    raise RuntimeError(
        "No audio playback method found.\n"
        "Either install ffplay-capable ffmpeg, or run:\n"
        "  pkg install termux-api\n"
        "and install the 'Termux:API' app from F-Droid/Play Store,\n"
        "which provides termux-media-player for audio playback."
    )


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

def play(image, lyrics_path=None, audio=None, cols=None, fps=12.0, square=True,
         style="threshold", threshold=128, renderer="braille", regions_path=None,
         audio_delay=0.0, skip_zoom_wait=False, layout="panel"):
    """Show the portrait with lyrics. Only `image` is required: with no audio
    the lyric timeline simply loops on its own clock, with no lyrics the
    portrait just stays up. Returns when the audio ends or on Ctrl+C.

    layout="panel":   portrait on top; under it a spinning record and the
                      lyrics as real terminal text (needs the braille renderer)
    layout="overlay": lyrics drawn big and black on the face itself
    """
    ensure_terminal_size(skip=skip_zoom_wait)

    term_size = shutil.get_terminal_size((80, 40))
    term_cols, term_lines = term_size.columns, term_size.lines

    use_panel = (layout == "panel" and renderer == "braille")
    plan = None
    if use_panel:
        import panel
        plan = panel.plan_layout(term_cols, term_lines)
        if cols:                                  # explicit --cols wins for the portrait
            plan["portrait_cols"] = cols
            plan["portrait_rows"] = cols // 2
            plan["portrait_left"] = max(0, (term_cols - cols) // 2)
        cols = plan["portrait_cols"]
    elif not cols:
        # size the square canvas by terminal HEIGHT as well as width, so the
        # frame never ends up taller than the screen (which would scroll it);
        # 2 lines are reserved for the prompt that reappears afterwards
        cols = max(20, min(term_cols, (term_lines - 2) * 2))

    regions = DEFAULT_REGIONS
    if regions_path:
        with open(regions_path) as f:
            regions = json.load(f)

    engine = PortraitEngine(image, cols, regions, square=square, style=style,
                             threshold=threshold, renderer=renderer)
    lyrics = load_lyrics(lyrics_path) if lyrics_path else []
    duration = get_duration(audio) if audio else None

    # diagnostics go to the normal screen (before the alt-screen swap) so
    # they stay readable in scrollback after the player exits
    print(f"[diagnostic] image: {image}")
    print(f"[diagnostic] lyrics: {len(lyrics)} entries"
          + (f" from {lyrics_path}" if lyrics_path else " (none)"))
    print(f"[diagnostic] audio: {audio or 'none (silent loop)'}"
          + (f", {duration:.1f}s" if duration else "")
          + f", audio-delay offset {audio_delay}s")
    print(f"[diagnostic] layout: {'panel' if use_panel else 'overlay'}"
          + ("" if use_panel or layout != "panel" else " (panel needs --renderer braille)"))
    time.sleep(1)

    if audio:
        audio_proc, started = start_audio(audio)
    else:
        audio_proc, started = _NullProc(), time.time()
    t0 = started + audio_delay

    # no audio: loop the lyric timeline so there is still something to watch
    loop_len = (lyrics[-1]["end"] + 1.0) if (not audio and lyrics) else None

    frame_interval = 1.0 / fps

    if use_panel:
        screen = panel.PanelLayout(plan)
        base_arr = np.array(engine.base)
        base_lines = braille_lines(base_arr)      # the portrait never changes...

    # the alternate screen buffer gives a fixed viewport that cannot scroll
    # out from under the repeated cursor-home redraws
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
    sys.stdout.flush()

    try:
        while True:
            frame_start = time.time()
            elapsed = frame_start - t0
            if audio and duration and elapsed > duration + 0.5:
                break
            if loop_len and elapsed > loop_len:
                t0 = frame_start
                elapsed = 0.0

            if use_panel:
                shown_t = max(0.0, elapsed)
                lines = base_lines
                if random.random() < 0.04:        # ...except for the occasional glitch
                    glitched = apply_glitch_rows(base_arr.astype(np.int16), chance=1.0)
                    lines = braille_lines(glitched)
                frame = screen.compose(
                    lines,
                    screen.disk_lines(shown_t * panel.DEG_PER_SEC),
                    screen.text.rows(lyrics, shown_t, duration))
            else:
                canvas = engine.base.copy()
                active = [e for e in lyrics if e["start"] <= elapsed <= e["end"]]
                for entry in active:
                    draw_lyric(canvas, engine, entry, elapsed)

                arr = np.array(canvas).astype(np.int16)
                arr = apply_scanlines(arr)
                arr = apply_flicker(arr)
                arr = apply_glitch_rows(arr)
                arr = np.clip(arr, 0, 255)
                frame = "\x1b[H" + render_frame(arr, renderer=renderer)

            sys.stdout.write(frame)
            sys.stdout.flush()

            time.sleep(max(0.0, frame_interval - (time.time() - frame_start)))
    except KeyboardInterrupt:
        pass
    finally:
        audio_proc.terminate()
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="Play a portrait with lyrics (CLI; "
                                 "use termviz.py for the dashboard)")
    ap.add_argument("--image", required=True)
    ap.add_argument("--lyrics", default=None, help="optional lyrics (.json or .lrc)")
    ap.add_argument("--audio", default=None, help="optional music file")
    ap.add_argument("--regions", default=None,
                     help="optional JSON file overriding DEFAULT_REGIONS")
    ap.add_argument("--cols", type=int, default=None,
                     help="defaults to fit the terminal")
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--no-square", action="store_true",
                     help="use full rectangular frame instead of centered square")
    ap.add_argument("--style", default="threshold",
                     choices=["dither", "threshold", "threshold-soft"],
                     help="black/white conversion style (default: threshold)")
    ap.add_argument("--threshold", type=int, default=128,
                     help="cutoff 0-255 for threshold styles; lower = more white")
    ap.add_argument("--renderer", default="braille", choices=["halfblock", "braille"],
                     help="braille = 4x pixel density (default)")
    ap.add_argument("--layout", default="panel", choices=["panel", "overlay"],
                     help="panel = record + lyrics under the portrait (default); "
                          "overlay = lyrics on the face")
    ap.add_argument("--skip-zoom-wait", action="store_true",
                     help="don't pause at startup asking to zoom out for more resolution")
    ap.add_argument("--audio-delay", type=float, default=0.0,
                     help="shift lyric timing by N seconds (+/-); positive = lyrics later")
    args = ap.parse_args()

    play(args.image, lyrics_path=args.lyrics, audio=args.audio, cols=args.cols,
         fps=args.fps, square=not args.no_square, style=args.style,
         threshold=args.threshold, renderer=args.renderer,
         regions_path=args.regions, audio_delay=args.audio_delay,
         skip_zoom_wait=args.skip_zoom_wait, layout=args.layout)


if __name__ == "__main__":
    main()
