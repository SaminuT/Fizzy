"""The global talk hotkey (press / release) and Esc to stop."""

from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


def parse(combo: str) -> list[str]:
    keys = [k.strip().lower() for k in combo.replace(" ", "").split("+") if k.strip()]
    aliases = {"win": "windows", "cmd": "windows", "super": "windows", "control": "ctrl", "option": "alt"}
    return [aliases.get(k, k) for k in keys]


class Hotkey(QObject):
    """Emits pressed when the whole combo is down and released when any part lets go.

    The keyboard hook runs on its own thread; Qt queues the signals over to
    the GUI thread.
    """

    pressed = pyqtSignal()
    released = pyqtSignal()
    escape = pyqtSignal()

    def __init__(self, combo: str, parent=None):
        super().__init__(parent)
        self.keys = parse(combo)
        self._down = False
        self._lock = threading.Lock()
        self._hook = None

    def start(self) -> None:
        import keyboard
        # The last key in the combo triggers; suppress it so e.g. Space
        # isn't typed into the user's app.
        keyboard.add_hotkey("+".join(self.keys), self._on_press, suppress=True, trigger_on_release=False)
        keyboard.add_hotkey("esc", self.escape.emit, suppress=False)
        self._hook = keyboard.hook(self._on_any)
        log.info("hotkey %s ready", "+".join(self.keys))

    def stop(self) -> None:
        import keyboard
        keyboard.unhook_all_hotkeys()
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None

    def change(self, combo: str) -> None:
        self.stop()
        self.keys = parse(combo)
        self.start()

    def _on_press(self) -> None:
        with self._lock:
            if self._down:
                return      # key repeat
            self._down = True
        self.pressed.emit()

    def _on_any(self, event) -> None:
        if event.event_type != "up":
            return
        name = (event.name or "").lower()
        if not _matches(name, self.keys):
            return
        with self._lock:
            if not self._down:
                return
            self._down = False
        self.released.emit()


def _matches(name: str, keys: list[str]) -> bool:
    # keyboard reports sided names ("left ctrl", "right windows").
    for k in keys:
        if name == k or name.endswith(" " + k):
            return True
    return False
