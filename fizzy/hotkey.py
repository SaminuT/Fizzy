"""Global hotkeys: talk (press / release), Esc to stop, and show/hide the panel."""

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
        self._handles: list = []

    def start(self) -> None:
        import keyboard
        # The last key in the combo triggers; suppress it so e.g. Space
        # isn't typed into the user's app.
        self._handles = [
            keyboard.add_hotkey("+".join(self.keys), self._on_press, suppress=True, trigger_on_release=False),
            keyboard.add_hotkey("esc", self.escape.emit, suppress=False),
        ]
        self._hook = keyboard.hook(self._on_any)
        log.info("hotkey %s ready", "+".join(self.keys))

    def stop(self) -> None:
        import keyboard
        _remove(self._handles)
        self._handles = []
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


class ToggleHotkey(QObject):
    """A single shortcut that fires once per press (e.g. show / hide the panel).

    before() runs at the moment of the press, while the user's app still has
    focus (the time to read its selection), and pressed fires after it. It
    runs on a separate thread: the keyboard hook itself must return at once,
    or Windows stalls every keystroke behind it.
    """

    pressed = pyqtSignal()

    def __init__(self, combo: str, before=None, parent=None):
        super().__init__(parent)
        self.combo = "+".join(parse(combo))
        self.before = before
        self._handles: list = []

    def start(self) -> None:
        import keyboard
        self._handles = [keyboard.add_hotkey(self.combo, self._fire, suppress=True, trigger_on_release=False)]
        log.info("panel hotkey %s ready", self.combo)

    def stop(self) -> None:
        _remove(self._handles)
        self._handles = []

    def change(self, combo: str) -> None:
        self.stop()
        self.combo = "+".join(parse(combo))
        self.start()

    def _fire(self) -> None:
        threading.Thread(target=self._run_before_then_emit, name="fizzy-panel-hotkey", daemon=True).start()

    def _run_before_then_emit(self) -> None:
        if self.before is not None:
            try:
                self.before()
            except Exception:
                log.debug("panel hotkey pre-step failed", exc_info=True)
        self.pressed.emit()


def _remove(handles: list) -> None:
    import keyboard
    for h in handles:
        try:
            keyboard.remove_hotkey(h)
        except (KeyError, ValueError):
            pass


def _matches(name: str, keys: list[str]) -> bool:
    # keyboard reports sided names ("left ctrl", "right windows").
    for k in keys:
        if name == k or name.endswith(" " + k):
            return True
    return False
