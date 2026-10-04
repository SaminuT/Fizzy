"""Remembers the last window the user worked in before switching to Fizzy.

When you click into Fizzy's panel to type, Fizzy itself becomes the
foreground window. The question is still about the app you were in a moment
ago, so this polls the foreground window and keeps the latest one that
isn't Fizzy.
"""

from __future__ import annotations

import os
import threading

from PyQt6.QtCore import QObject, QTimer

from fizzy.context import window
from fizzy.context.window import EMPTY, WindowInfo

POLL_MS = 400


class ForegroundTracker(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._last: WindowInfo = EMPTY
        self._pid = os.getpid()
        self._timer = QTimer(self, interval=POLL_MS)
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        self.poll()
        self._timer.start()

    def poll(self) -> None:
        win = window.foreground()
        if win.hwnd and win.pid != self._pid:
            with self._lock:
                self._last = win
            self.on_external(win)

    def on_external(self, win: WindowInfo) -> None:
        """Hook for subclasses; runs on the GUI thread every poll."""

    def current(self) -> WindowInfo:
        """The window a question is about: the foreground one unless that's Fizzy."""
        win = window.foreground()
        if win.hwnd and win.pid != self._pid:
            return win
        with self._lock:
            return self._last
