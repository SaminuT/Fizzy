"""Fizzy's entry point."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from fizzy import APP_NAME, __version__, logs

log = logging.getLogger("fizzy")


def main() -> int:
    logs.setup()
    log.info("%s %s starting", APP_NAME, __version__)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    return app.exec()
