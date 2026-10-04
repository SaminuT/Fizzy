"""Which window the user is working in."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    exe: str            # lower-case file name, e.g. "chrome.exe"
    pid: int

    @property
    def app_key(self) -> str:
        """Groups conversation history per application."""
        return self.exe or self.title or "unknown"


EMPTY = WindowInfo(0, "", "", 0)


def foreground() -> WindowInfo:
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return EMPTY
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return EMPTY
    return describe(hwnd)


def describe(hwnd: int) -> WindowInfo:
    user32 = ctypes.windll.user32
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return WindowInfo(int(hwnd), buf.value or "", _exe_name(pid.value), pid.value)


def _exe_name(pid: int) -> str:
    if not pid:
        return ""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def own_process() -> int:
    return os.getpid()
