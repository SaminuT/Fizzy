"""System-tray icon and menu."""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from fizzy import APP_NAME, __version__
from fizzy.paths import data_dir
from fizzy.ui.theme import app_icon


class Tray(QObject):
    show_panel = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.builder = None
        self.icon = QSystemTrayIcon(app_icon(), self)
        self.icon.setToolTip(f"{APP_NAME} {__version__}")
        self.menu = QMenu()
        self._build()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)

    def _build(self) -> None:
        self.menu.clear()
        show = QAction("Show panel", self.menu)
        show.triggered.connect(self.show_panel.emit)
        self.menu.addAction(show)
        self.menu.addSeparator()
        self.populate(self.menu)
        self.menu.addSeparator()
        folder = QAction("Open data folder", self.menu)
        folder.triggered.connect(lambda: os.startfile(data_dir()))
        self.menu.addAction(folder)
        quit_ = QAction(f"Quit {APP_NAME}", self.menu)
        quit_.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(quit_)

    def populate(self, menu: QMenu) -> None:
        if self.builder is not None:
            self.builder(menu)

    def set_builder(self, builder) -> None:
        """builder(menu) adds the feature menus between Show and Quit."""
        self.builder = builder
        self._build()

    def rebuild(self) -> None:
        self._build()

    def show(self) -> None:
        self.icon.show()

    def notify(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message, app_icon(), 6000)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_panel.emit()


def tray_available() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable() and QApplication.instance() is not None
