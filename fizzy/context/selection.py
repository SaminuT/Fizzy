"""Read the text the user has highlighted in another app.

Two ways, tried in order:

1. UI Automation. Ask the focused control for its current selection
   through the TextPattern interface. Instant, and it never touches the
   clipboard. Works in most real apps: Word, Notepad, browsers, editors, PDFs.
2. Clipboard. Save the clipboard, send Ctrl+C, read the result, put the old
   clipboard back. Works almost everywhere, so it's the fallback. It's skipped
   in terminals, where Ctrl+C interrupts the running program, and when the
   clipboard holds something other than plain text that we couldn't restore.

Both block, so call them from a worker thread.
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import Optional

from fizzy.context.window import WindowInfo

log = logging.getLogger(__name__)

MAX_CHARS = 12_000

TERMINALS = {
    "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "openconsole.exe",
    "wezterm-gui.exe", "alacritty.exe", "mintty.exe", "kitty.exe", "hyper.exe", "tabby.exe",
    "putty.exe", "kitty_portable.exe", "mobaxterm.exe", "warp.exe",
}

# Standard clipboard formats that are just text, so restoring the Unicode
# text alone loses nothing important.
_CF_TEXT, _CF_OEMTEXT, _CF_UNICODETEXT, _CF_LOCALE = 1, 7, 13, 16
_TEXT_FORMATS = {_CF_TEXT, _CF_OEMTEXT, _CF_UNICODETEXT, _CF_LOCALE}


def read_selection(win: WindowInfo, allow_clipboard: bool = True) -> Optional[str]:
    text = read_uia()
    if text is None and allow_clipboard and clipboard_allowed(win):
        text = read_via_clipboard()
    return clean(text)


def clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return None
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[…selection cut short]"
    return text


# ── UI Automation ───────────────────────────────────────────────────────

def read_uia() -> Optional[str]:
    try:
        import uiautomation as auto
    except ImportError:
        return None
    try:
        with auto.UIAutomationInitializerInThread(debug=False):
            ctrl = auto.GetFocusedControl()
            # The focused element is sometimes a child (a caret, a span) of
            # the control that actually owns the text; walk up a little.
            for _ in range(4):
                if ctrl is None:
                    break
                pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
                if pattern is not None:
                    ranges = pattern.GetSelection() or []
                    text = "".join(r.GetText(MAX_CHARS + 1) for r in ranges)
                    return text or None
                ctrl = ctrl.GetParentControl()
    except Exception:
        log.debug("UIA selection read failed", exc_info=True)
    return None


# ── Clipboard fallback ──────────────────────────────────────────────────

def clipboard_allowed(win: WindowInfo) -> bool:
    return win.exe not in TERMINALS


def _wait_for_modifiers_up(timeout: float = 1.5) -> bool:
    """Ctrl+C with the user's hotkey still held would become a different shortcut."""
    import keyboard
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(keyboard.is_pressed(k) for k in ("ctrl", "alt", "shift", "windows")):
            return True
        time.sleep(0.02)
    return False


def read_via_clipboard(wait: float = 0.45) -> Optional[str]:
    import keyboard
    import win32clipboard as cb

    saved = _snapshot_text_clipboard()
    if saved is _UNRESTORABLE:
        log.info("clipboard holds non-text data; not using the copy fallback")
        return None
    if not _wait_for_modifiers_up():
        return None

    user32 = ctypes.windll.user32
    before = user32.GetClipboardSequenceNumber()
    keyboard.send("ctrl+c")
    deadline = time.monotonic() + wait
    while user32.GetClipboardSequenceNumber() == before and time.monotonic() < deadline:
        time.sleep(0.015)
    if user32.GetClipboardSequenceNumber() == before:
        return None     # nothing was selected, so nothing was copied

    text = None
    try:
        if _open(cb):
            try:
                if cb.IsClipboardFormatAvailable(_CF_UNICODETEXT):
                    text = cb.GetClipboardData(_CF_UNICODETEXT)
            finally:
                cb.CloseClipboard()
    finally:
        _restore_text_clipboard(saved)
    return text


_UNRESTORABLE = object()


def _open(cb, tries: int = 10) -> bool:
    # Another app may hold the clipboard open for a moment.
    for _ in range(tries):
        try:
            cb.OpenClipboard(None)
            return True
        except Exception:
            time.sleep(0.02)
    return False


def _snapshot_text_clipboard():
    """The clipboard's text, None if empty, or _UNRESTORABLE."""
    import win32clipboard as cb
    if not _open(cb):
        return _UNRESTORABLE
    try:
        formats = []
        fmt = cb.EnumClipboardFormats(0)
        while fmt:
            formats.append(fmt)
            fmt = cb.EnumClipboardFormats(fmt)
        if not formats:
            return None
        if any(not _is_texty(cb, f) for f in formats):
            return _UNRESTORABLE
        if _CF_UNICODETEXT in formats:
            return cb.GetClipboardData(_CF_UNICODETEXT)
        return None
    finally:
        cb.CloseClipboard()


# Registered formats that browsers and editors add alongside plain text.
# Restoring only the plain text drops their formatting, which is acceptable.
_TEXTY_NAMES = ("html", "rich text", "rtf", "text/", "chromium", "moz", "vscode-editor-data",
                "msdevcolumnselect", "locale")


def _is_texty(cb, fmt: int) -> bool:
    if fmt in _TEXT_FORMATS:
        return True
    if fmt < 0xC000:
        return False        # bitmaps, files, metafiles…
    try:
        name = cb.GetClipboardFormatName(fmt).lower()
    except Exception:
        return False
    return any(t in name for t in _TEXTY_NAMES)


def _restore_text_clipboard(saved) -> None:
    import win32clipboard as cb
    if not _open(cb):
        log.warning("couldn't reopen the clipboard to restore it")
        return
    try:
        cb.EmptyClipboard()
        if saved:
            cb.SetClipboardData(_CF_UNICODETEXT, saved)
    finally:
        cb.CloseClipboard()
