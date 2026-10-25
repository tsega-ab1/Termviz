# termviz — retro terminal portrait visualizer

A black-and-white, braille-dot portrait that runs inside a terminal (built
and tested in Termux on Android), with lyric text drawn big and centered
on the face.

## Files

| File | Purpose |
|---|---|
| `render.py` | Core engine + full player (portrait + lyrics + audio) |
| `view_continuous.py` | Loops the lyric animation on its own clock, **no audio** |
| `view_portrait.py` | Static single-frame portrait check |
| `view_text.py` | Static single-line text-on-portrait check |
| `view_regions.py`, `calibrate.py` | Legacy region tools (regions are no longer used by `draw_lyric`) |
| `convert_lyrics.py` | Converts whisper-style transcript JSON into the flat lyrics format |
| `launch.sh`, `setup.sh` | Launcher and Termux package setup |
| `lyrics_example.json` | Format template with placeholder text |

## Setup (Termux)

```bash
pkg install -y python ffmpeg python-numpy python-pillow
```

Use the `pkg` builds of numpy/Pillow. `pip install numpy` tries to compile
from source on Android and fails.

## Run

```bash
# animation only, no audio
python view_continuous.py --image portrait.jpg --lyrics lyrics.json

# full player
python render.py --image portrait.jpg --lyrics lyrics.json --audio song.m4a
```

## Lyrics format

```json
[
  {"start": 2.5, "end": 5.0, "text": "YOUR LINE HERE", "effect": "typewriter"}
]
```

`effect` is one of `hold`, `typewriter`, `fade`, `glitch`. Text is always the
same size, centered, and black.

## Useful flags

- `--renderer braille|halfblock` — braille (default) gives 4x the pixel density
- `--style threshold|threshold-soft|dither` — black/white conversion style
- `--cols N` — override auto-sizing from the terminal
- `--audio-delay S` — shift lyric timing against the audio
- `--skip-zoom-wait` — don't pause asking you to pinch-zoom out

## Notes

- Termux's font size can't be set from a script. Pinch-zoom out for a denser render.
- Audio uses `ffplay` if present, otherwise `termux-media-player`.
- Your portrait, audio and timed lyric files are git-ignored on purpose.
