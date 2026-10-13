"""How well a piece of on-screen text matches what the user asked for."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_SHORTCUT = re.compile(r"\s*\((?:ctrl|alt|shift|win)[^)]*\)|\s+(?:ctrl|alt|shift)\+\S+$", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w\s]+")


def normalise(text: str) -> str:
    t = text.replace("&", "")               # menu accelerators: "&File"
    t = _SHORTCUT.sub("", t)
    t = _NON_WORD.sub(" ", t.lower())
    return " ".join(t.split())


def score(target: str, candidate: str) -> float:
    """0..1. Exact match 1.0; whole-word containment high; otherwise fuzzy."""
    a, b = normalise(target), normalise(candidate)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    words_a, words_b = a.split(), b.split()
    if all(w in words_b for w in words_a):
        # Every asked-for word is there; penalise long labels that just contain them.
        return 0.92 - min(0.25, 0.03 * (len(words_b) - len(words_a)))
    if re.search(rf"\b{re.escape(a)}\b", b):
        # The phrase is in there as whole words, among other text.
        return max(0.6, 0.85 - 0.01 * (len(b) - len(a)))
    return SequenceMatcher(None, a, b).ratio() * 0.9
