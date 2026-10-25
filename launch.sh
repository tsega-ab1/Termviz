#!/data/data/com.termux/files/usr/bin/bash
# Launcher for the terminal visualizer.
#
# Usage:
#   bash launch.sh path/to/portrait.jpg path/to/lyrics.json path/to/song.mp3 [regions.json]

set -e

IMG="$1"
LYRICS="$2"
AUDIO="$3"
REGIONS="$4"

if [[ -z "$IMG" || -z "$LYRICS" || -z "$AUDIO" ]]; then
    echo "Usage: bash launch.sh <image> <lyrics.json> <audio> [regions.json]"
    exit 1
fi

cleanup() {
    pkill -f ffplay 2>/dev/null || true
    printf "\x1b[0m\x1b[2J\x1b[H"
}
trap cleanup EXIT INT TERM

if [[ -n "$REGIONS" ]]; then
    python render.py --image "$IMG" --lyrics "$LYRICS" --audio "$AUDIO" --regions "$REGIONS"
else
    python render.py --image "$IMG" --lyrics "$LYRICS" --audio "$AUDIO"
fi
