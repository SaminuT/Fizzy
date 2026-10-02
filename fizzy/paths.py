"""Where Fizzy keeps its files on disk."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """%LOCALAPPDATA%\\Fizzy, or FIZZY_HOME when set (handy for tests)."""
    override = os.environ.get("FIZZY_HOME")
    if override:
        base = Path(override)
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Fizzy"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(exist_ok=True)
    return d


def log_file() -> Path:
    return data_dir() / "fizzy.log"
