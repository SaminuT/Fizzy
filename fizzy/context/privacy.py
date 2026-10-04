"""Decide when a window is too sensitive to capture."""

from __future__ import annotations

import re

from fizzy.context.window import WindowInfo

# Apps whose whole purpose is secrets.
SENSITIVE_APPS = {
    "1password.exe", "bitwarden.exe", "keepass.exe", "keepassxc.exe", "lastpass.exe",
    "dashlane.exe", "enpass.exe", "nordpass.exe", "roboform.exe", "protonpass.exe",
    "credentialuibroker.exe", "consent.exe", "logonui.exe",
}

# Words in a window title that suggest passwords, money or sign-in.
_TITLE = re.compile(
    r"\b(password|passcode|passkey|sign[ -]?in|log[ -]?in|2fa|two[- ]factor|one[- ]time code|"
    r"verification code|bank(ing)?|credit card|card details|checkout|payment|wallet|seed phrase|"
    r"recovery (key|phrase)|private key|vault)\b",
    re.IGNORECASE,
)


def is_sensitive(win: WindowInfo) -> bool:
    if win.exe in SENSITIVE_APPS:
        return True
    return bool(_TITLE.search(win.title))
