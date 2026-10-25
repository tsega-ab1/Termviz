#!/data/data/com.termux/files/usr/bin/bash
# One-time setup for the terminal visualizer on Termux.
# Run with: bash setup.sh

set -e

echo "== Updating Termux packages =="
pkg update -y && pkg upgrade -y

echo "== Installing system packages =="
pkg install -y python ffmpeg

echo "== Letting Termux access your phone's storage (photos/music) =="
termux-setup-storage
echo "   -> A permission popup should appear. Approve it, then re-run this"
echo "      script if it failed silently."

echo "== Installing Python packages =="
pip install --upgrade pip
pip install pillow numpy

echo "== Done =="
echo "Your shared storage is now reachable at: ~/storage/shared"
echo "e.g. a photo at Phone/DCIM/portrait.jpg is:"
echo "  ~/storage/shared/DCIM/portrait.jpg"
