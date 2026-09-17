"""Violent-list file loading. Kept separate so Classifier stays pure."""
from __future__ import annotations

import os


def load_violent(path):
    entries, name, patterns, in_patterns = [], None, [], False
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    for line in lines:
        s = line.strip()
        if s.startswith("## "):
            if name and patterns:
                entries.append({"name": name, "patterns": patterns})
            name, patterns, in_patterns = s[3:].strip(), [], False
        elif s.lower().startswith("patterns:"):
            in_patterns = True
        elif in_patterns and s.startswith("-"):
            patterns.append(s[1:].strip())
        elif s and not s.startswith("#"):
            in_patterns = False
    if name and patterns:
        entries.append({"name": name, "patterns": patterns})
    return entries


def mtime_ns(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1
