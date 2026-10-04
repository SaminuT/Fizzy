"""Small Win32 helpers for Fizzy's own windows."""

from __future__ import annotations

import ctypes
import logging

log = logging.getLogger(__name__)

_WDA_EXCLUDEFROMCAPTURE = 0x11
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000


def exclude_from_capture(widget) -> None:
    """Keep this window out of screenshots (Windows 10 2004 and later).

    Fizzy's panel and buddy would otherwise show up in every screenshot it
    takes and cover what the user is asking about.
    """
    try:
        ok = ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), _WDA_EXCLUDEFROMCAPTURE)
        if not ok:
            log.debug("SetWindowDisplayAffinity failed for %s", widget)
    except AttributeError:
        pass


def no_activate(widget) -> None:
    """Clicking this window won't steal focus from the user's app."""
    try:
        user32 = ctypes.windll.user32
        hwnd = int(widget.winId())
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_NOACTIVATE)
    except AttributeError:
        pass
