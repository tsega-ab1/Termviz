# termviz — retro terminal portrait visualizer

A black-and-white, braille-dot portrait that runs inside a terminal (built
and tested in Termux on Android). Under the portrait a vinyl record spins
while the lyrics type out beside it as real terminal text.

```
        portrait (braille)
 ─────────────────────────────────
  [ spinning record ]   previous line (dim)
                        CURRENT LINE (typed out)
                        next line (dim)
                        0:42 ━━━●──── 3:21
```

## Files

| File | Purpose |
|---|---|
| `termviz.py` | **Start here.** Opens the dashboard, plays, returns to the dashboard |
| `dashboard.py` | Terminal dashboard: pick image / music / lyrics, preview, Play |
| `lyrics_io.py` | Reads lyrics from flat JSON, whisper-style JSON or `.lrc` |
| `render.py` | Core engine + `play()` (portrait + lyrics + optional audio) |
| `panel.py` | The panel layout: spinning record, lyric text, progress bar |
| `braille.py` | Fast numpy pixel-array -> braille conversion |
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
python termviz.py
```

The dashboard lists the images, music and lyrics it finds in the current
folder, `~/storage/shared/{Download,Music,DCIM,Pictures,Documents}` and
`~`. Press `1`, `2` or `3` to choose one (or paste a path), `4` to play.
Only the image is required: with no music the lyrics loop silently, with no
lyrics the portrait just stays up. Picking a song auto-attaches a lyrics
file with the same name (`song.m4a` + `song.lrc`). Your last choices are
remembered in `~/.termviz.json`. Ctrl+C stops playback and returns to the
dashboard.

Layouts: `--layout panel` (default) puts the record and lyrics under the
portrait; `--layout overlay` draws the lyrics big and black on the face
instead. The panel needs the braille renderer (the default).

Skip the dashboard:

```bash
python termviz.py --image portrait.jpg --music song.m4a --lyrics song.lrc --play
python render.py  --image portrait.jpg --lyrics lyrics.json --audio song.m4a   # old CLI
```

## Lyrics format

```json
[
  {"start": 2.5, "end": 5.0, "text": "YOUR LINE HERE", "effect": "typewriter"}
]
```

In the panel layout every line types itself out and the `effect` field is
ignored. In the overlay layout `effect` is one of `hold`, `typewriter`,
`fade`, `glitch`, and the text is always the same size, centered, and black.

The same fields work in a whisper-style file (`{"segments": [...]}`), and
`.lrc` files (`[mm:ss.xx]text`) are read directly, so `convert_lyrics.py` is
no longer needed for playback.

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

## Mini bar (work while it plays)

`python3 termviz.py` -> pick image / music / lyrics -> **4 Play in mini bar**.

Termviz opens a slim bar at the top of a tmux window (record on the left, lyrics
and controls in the middle, portrait on the right). Everything below it is a normal
shell, so vim, git, etc. keep working in the same terminal.

| key | action |
|---|---|
| `F7` / `Space` | pause / resume |
| `F6` / `p` | previous (restart if past 3 s) |
| `F8` / `n` | next track (the other songs in the same folder) |
| `Left` / `Right` | seek -/+ 10 s (bar focused: `Ctrl-b` then `Up`) |
| `q` | close the bar |

Needs `tmux` and `ffplay` (`sudo apt install tmux ffmpeg`). The F-keys work from
any pane. Use `--bar-rows N` for a taller or shorter bar, or **5** in the
dashboard for the old full-screen player.

## Finding files

In the dashboard's picker: type part of a name to search every folder under your
home (and mounted drives), `*` to list everything, or type a path and press Tab
to complete it.

## Image detail

The default `--style detail` (sharpen + Atkinson dither) keeps far more detail than
`threshold`. Other styles are still available with `--style`.
