"""Point tags the model writes into its answer, and how to keep them out of sight.

Format (one per thing to point at):

    {{point x=512 y=330 label="Save"}}
    {{point x=512 y=330 screen=2 label="Save"}}

x and y are on a 0–1000 grid over the screenshot; screen is the
screenshot's number when several were sent (default 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TAG = re.compile(r"\{\{\s*point\b([^}]*)\}\}", re.IGNORECASE)
_ATTR = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s}]+))')


@dataclass(frozen=True)
class PointTag:
    x: float
    y: float
    screen: int = 1
    label: str = ""


def parse_tag(body: str) -> PointTag | None:
    attrs = {}
    for m in _ATTR.finditer(body):
        attrs[m.group(1).lower()] = next(g for g in m.groups()[1:] if g is not None)
    try:
        x, y = float(attrs["x"]), float(attrs["y"])
    except (KeyError, ValueError):
        return None
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None
    try:
        screen = int(attrs.get("screen", 1))
    except ValueError:
        screen = 1
    return PointTag(x, y, max(1, screen), attrs.get("label", "").strip())


def strip_tags(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", TAG.sub("", text)).strip()


class TagFilter:
    """Streams text through, holding back anything that might be a tag.

    feed() returns (text safe to show now, tags completed in this chunk).
    """

    def __init__(self):
        self._held = ""

    def feed(self, chunk: str) -> tuple[str, list[PointTag]]:
        buf = self._held + chunk
        tags: list[PointTag] = []
        out: list[str] = []
        pos = 0
        for m in TAG.finditer(buf):
            out.append(buf[pos:m.start()])
            tag = parse_tag(m.group(1))
            if tag:
                tags.append(tag)
            pos = m.end()
        rest = buf[pos:]
        # Hold back a trailing "{" or "{{…" that could still become a tag.
        cut = rest.find("{{")
        if cut < 0 and rest.endswith("{"):
            cut = len(rest) - 1
        if cut >= 0 and "}}" not in rest[cut:]:
            out.append(rest[:cut])
            self._held = rest[cut:]
            if len(self._held) > 200:       # not a tag after all
                out.append(self._held)
                self._held = ""
        else:
            out.append(rest)
            self._held = ""
        return "".join(out), tags

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held


POINTING_PROMPT = """
Pointing:
- When the user asks where something is, or which thing to click, point at it on the screenshot by writing a tag like {{point x=512 y=330 label="Save"}} once, right after you first mention it. x and y are on a 0–1000 grid over the screenshot (0,0 is the top-left corner, 1000,1000 the bottom-right). Aim at the centre of the control. Add screen=2 (and so on) when several screenshots were attached and it's on another one.
- The label is two or three words naming the thing. Point only at things you can actually see; if it isn't visible, say where to look instead.
- If a "found on screen" location is given below, use exactly those numbers.
""".strip()
