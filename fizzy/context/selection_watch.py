"""Keep the latest highlighted text from the app the user was in.

Typed questions are asked from Fizzy's own panel, and by then the user's app
no longer has focus. This watcher reads the selection (UI Automation only,
never the clipboard) in the background while another app is in front, so the
panel can offer "use the highlighted text" when the user switches over.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from fizzy.context import selection, window

log = logging.getLogger(__name__)

POLL_S = 0.8
FRESH_S = 90        # older selections aren't offered


@dataclass(frozen=True)
class Selected:
    text: str
    hwnd: int
    at: float


class SelectionWatcher(QObject):
    changed = pyqtSignal(str)       # "" when the selection went away

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._latest: Optional[Selected] = None
        self._pid = os.getpid()
        self._enabled = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="fizzy-selection", daemon=True)

    def start(self, enabled: bool) -> None:
        self.set_enabled(enabled)
        self._thread.start()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()
            self._set(None)

    def stop(self) -> None:
        self._stop.set()
        self._enabled.set()

    def latest_for(self, hwnd: int) -> Optional[str]:
        with self._lock:
            s = self._latest
        if s and s.hwnd == hwnd and time.monotonic() - s.at < FRESH_S:
            return s.text
        return None

    def clear(self) -> None:
        self._set(None)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._enabled.wait()
            if self._stop.is_set():
                break
            try:
                win = window.foreground()
                if win.hwnd and win.pid != self._pid:
                    text = selection.clean(selection.read_uia())
                    self._set(Selected(text, win.hwnd, time.monotonic()) if text else None)
            except Exception:
                log.debug("selection poll failed", exc_info=True)
            self._stop.wait(POLL_S)

    def _set(self, value: Optional[Selected]) -> None:
        with self._lock:
            before = self._latest.text if self._latest else ""
            self._latest = value
        after = value.text if value else ""
        if after != before:
            self.changed.emit(after)
