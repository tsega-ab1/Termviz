#!/usr/bin/env python3
"""Find files anywhere under your home folder (and mounted drives), plus
Tab-completion for typed paths. Used by the dashboard's file picker."""

import glob
import os
import time

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "site-packages", "proc", "sys",
             "dev", "snap", "build", "dist", "target", "cache"}


def roots():
    """Places worth searching: home, removable/mounted drives, Termux storage."""
    home = os.path.expanduser("~")
    user = os.path.basename(home)
    cands = [home, "/media", f"/media/{user}", f"/run/media/{user}", "/mnt",
             os.path.join(home, "storage", "shared")]
    seen, out = set(), []
    for c in cands:
        real = os.path.realpath(c)
        if os.path.isdir(real) and real not in seen:
            # skip a root that lives inside one we already have
            if not any(real.startswith(s + os.sep) for s in seen):
                seen.add(real)
                out.append(real)
    return out


def search(exts, query="", validator=None, limit=300, budget=6.0):
    """Recursive, case-insensitive name search.

    exts       set of lowercase extensions (".mp3", ...)
    query      words that must ALL appear in the file name ("" = everything)
    validator  optional fn(path)->bool for expensive content checks (lyrics)
    Returns (paths newest-first, stopped_early).
    """
    words = query.lower().split()
    deadline = time.time() + budget
    hits, seen, stopped = [], set(), False

    for root in roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d.lower() not in SKIP_DIRS]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                if os.path.splitext(fn)[1].lower() not in exts:
                    continue
                low = fn.lower()
                if words and not all(w in low for w in words):
                    continue
                path = os.path.join(dirpath, fn)
                real = os.path.realpath(path)
                if real not in seen:
                    seen.add(real)
                    hits.append(path)
            if time.time() > deadline:
                stopped = True
                break
        if stopped:
            break

    def mtime(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0

    hits.sort(key=mtime, reverse=True)
    if validator:
        ok = []
        for p in hits[:limit * 4]:
            if validator(p):
                ok.append(p)
                if len(ok) >= limit:
                    break
        return ok, stopped
    return hits[:limit], stopped


_completion_ready = False


def enable_path_completion():
    """Make Tab complete file paths at every input() prompt."""
    global _completion_ready
    if _completion_ready:
        return
    try:
        import readline
    except ImportError:
        return

    def complete(text, state):
        matches = []
        for m in sorted(glob.glob(os.path.expanduser(text) + "*")):
            matches.append(m + "/" if os.path.isdir(m) else m)
        return matches[state] if state < len(matches) else None

    readline.set_completer_delims(" \t\n")
    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")
    _completion_ready = True
