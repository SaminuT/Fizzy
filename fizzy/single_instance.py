"""Make sure only one Fizzy runs per Windows session."""

from __future__ import annotations

import ctypes

_ERROR_ALREADY_EXISTS = 183
_handle = None


def acquire() -> bool:
    """True if this is the only running Fizzy. Holds a named mutex until exit."""
    global _handle
    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:      # not Windows
        return True
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _handle = kernel32.CreateMutexW(None, False, "Local\\Fizzy.SingleInstance")
    return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
