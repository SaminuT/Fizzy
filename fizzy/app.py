"""Fizzy's entry point."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from fizzy import APP_NAME, __version__, logs, single_instance
from fizzy.settings import Settings
from fizzy.ui.theme import app_icon
from fizzy.ui.tray import Tray

log = logging.getLogger("fizzy")


class FizzyApp:
    def __init__(self, qt: QApplication):
        self.qt = qt
        self.settings = Settings.load()
        self.tray = Tray()
        self.tray.quit_requested.connect(self.quit)

    def start(self) -> None:
        self.tray.show()
        log.info("ready (provider=%s)", self.settings.provider)

    def quit(self) -> None:
        log.info("quitting")
        self.tray.icon.hide()
        self.qt.quit()


def main() -> int:
    logs.setup()
    log.info("%s %s starting", APP_NAME, __version__)
    qt = QApplication(sys.argv)
    qt.setApplicationName(APP_NAME)
    qt.setWindowIcon(app_icon())
    qt.setQuitOnLastWindowClosed(False)

    if not single_instance.acquire():
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running. Look for it in the system tray.")
        return 0

    app = FizzyApp(qt)
    app.start()
    return qt.exec()
