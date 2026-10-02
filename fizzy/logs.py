"""Logging to a rotating file in the data folder, plus stderr when there is one."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from fizzy.paths import log_file

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    file_handler = RotatingFileHandler(log_file(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    # A windowed build has no console, and sys.stderr is None there.
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(console)

    # Third-party HTTP clients are very chatty at INFO.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
