"""Collect what goes to the model alongside a question."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from fizzy.ai.base import Image
from fizzy.context import privacy, screen
from fizzy.context.screen import ScreenLayout, Shot
from fizzy.context.window import WindowInfo
from fizzy.settings import Settings

log = logging.getLogger(__name__)


@dataclass
class Context:
    window: WindowInfo
    shots: list[Shot] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    sensitive: bool = False

    @property
    def images(self) -> list[Image]:
        return [s.image for s in self.shots]


async def gather(settings: Settings, win: WindowInfo, want_screen: bool = True) -> Context:
    ctx = Context(window=win)
    now = datetime.now()
    ctx.lines.append(f"Today is {now:%A, %d %B %Y}; the local time is {now:%H:%M}.")
    if win.title or win.exe:
        ctx.lines.append(f"The user is working in the window \"{win.title}\" ({win.exe or 'unknown app'}).")

    ctx.sensitive = settings.privacy_guard and privacy.is_sensitive(win)
    if ctx.sensitive:
        ctx.lines.append(
            "Privacy guard: that window looks sensitive (passwords, payments or sign-in), so no screenshot "
            "was taken. Answer from the question alone and mention briefly that you skipped looking.")
        return ctx

    if want_screen:
        ctx.shots = await _screenshots(settings)
        ctx.lines += describe_shots(ctx.shots)
    return ctx


async def _screenshots(settings: Settings) -> list[Shot]:
    monitors = ScreenLayout.monitors()
    if not monitors:
        return []
    if not settings.all_monitors:
        m = screen.pointer_monitor(monitors)
        monitors = [m] if m else monitors[:1]
    try:
        return await asyncio.to_thread(screen.capture, monitors)
    except Exception:
        log.exception("screen capture failed")
        return []


def describe_shots(shots: list[Shot]) -> list[str]:
    if not shots:
        return []
    lines = []
    if len(shots) == 1:
        lines.append("The attached screenshot shows the user's screen right now.")
    else:
        lines.append(f"The {len(shots)} attached screenshots show the user's monitors, numbered 1 to {len(shots)} "
                     "in the order attached.")
    pos = screen.pointer_physical()
    if pos:
        for n, shot in enumerate(shots, start=1):
            if shot.monitor.contains(*pos):
                x, y = shot.physical_to_norm(*pos)
                where = f"screenshot {n}" if len(shots) > 1 else "the screenshot"
                lines.append(f"The mouse pointer is at x={x}, y={y} in {where}, on a 0–1000 grid "
                             "where 0,0 is the top-left corner.")
    return lines
