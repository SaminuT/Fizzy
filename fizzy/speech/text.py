"""Turn a written answer into something pleasant to hear."""

from __future__ import annotations

import re

_CODE_BLOCK = re.compile(r"```.*?(```|$)", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MARKER = re.compile(r"\{\{[^}]*\}\}")             # Fizzy's own {{point …}} tags
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~)(.+?)\1")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.MULTILINE)
_LATEX = re.compile(r"\\\(|\\\)|\\\[|\\\]|\$\$?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
_STEP = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")


def speakable(text: str) -> str:
    t = _MARKER.sub("", text)
    t = _CODE_BLOCK.sub(" (the code is in the panel) ", t)
    t = _LINK.sub(r"\1", t)
    t = _URL.sub("the link in the panel", t)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _TABLE_RULE.sub("", t)
    t = _HEADING.sub("", t)
    t = _BULLET.sub("", t)
    t = _EMPHASIS.sub(r"\2", t)
    t = _LATEX.sub("", t)
    t = t.replace("|", ", ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def sentences(text: str, max_len: int = 240) -> list[str]:
    """Split for streaming speech: the first clip starts sooner if it's short."""
    out: list[str] = []
    for line in speakable(text).split("\n"):
        line = line.strip()
        if not line:
            continue
        pieces = [p.strip() for p in _SENTENCE.split(line)]
        # "1. Open the menu" splits after "1."; glue the number back on.
        merged: list[str] = []
        for p in pieces:
            if merged and re.fullmatch(r"\d+[.)]", merged[-1]):
                merged[-1] = f"{merged[-1]} {p}"
            else:
                merged.append(p)
        for s in merged:
            while len(s) > max_len:
                cut = s.rfind(",", 0, max_len)
                cut = cut if cut > 40 else s.rfind(" ", 0, max_len)
                cut = cut if cut > 0 else max_len
                out.append(s[:cut + 1].strip())
                s = s[cut + 1:].strip()
            if s:
                out.append(s)
    return out


def split_steps(text: str) -> tuple[str, list[str]]:
    """'Intro\\n1. a\\n2. b' → ('Intro', ['a', 'b']). Lines after the list stay with the last step."""
    intro: list[str] = []
    steps: list[str] = []
    for line in text.splitlines():
        m = _STEP.match(line)
        if m:
            steps.append(m.group(2).strip())
        elif steps and line.strip():
            steps[-1] += "\n" + line.strip()
        elif not steps:
            intro.append(line)
    return "\n".join(intro).strip(), steps
