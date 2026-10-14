"""Find what a question asks about: UI Automation first, then OCR and the vision grid together.

UI Automation is exact and takes well under a second, so it goes alone.
OCR (a few seconds on a CPU) and the two-pass grid (two model calls) are
slower and independent, so they run side by side; a confident OCR hit wins,
otherwise the grid's answer is used.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from fizzy.ai.base import Provider
from fizzy.context.screen import Shot
from fizzy.context.window import WindowInfo
from fizzy.pointing import grid, ocr, uia
from fizzy.pointing.uia import Found

log = logging.getLogger(__name__)

UIA_TIMEOUT_S = 2.0
SLOW_TIMEOUT_S = 20.0


def warm_up() -> None:
    """Load the OCR model in the background so the first pointing question isn't slow."""
    if ocr.available():
        threading.Thread(target=ocr._ocr, name="fizzy-ocr-warmup", daemon=True).start()


def shot_for(found: Found, shots: list[Shot]) -> Optional[Shot]:
    for s in shots:
        if s.monitor.contains(found.x, found.y):
            return s
    return None


async def fast(win: WindowInfo, target: str, shots: list[Shot]) -> Optional[Found]:
    """UI Automation only. Results outside the captured monitors are ignored."""
    if not win.hwnd:
        return None
    try:
        found = await asyncio.wait_for(asyncio.to_thread(uia.find, win.hwnd, target), UIA_TIMEOUT_S)
    except asyncio.TimeoutError:
        return None
    if found and shots and shot_for(found, shots) is None:
        return None
    return found


async def slow(provider: Provider, model: Optional[str], shot: Shot, target: str) -> Optional[Found]:
    """OCR and the vision grid in parallel."""
    tasks = {asyncio.create_task(asyncio.to_thread(ocr.find, shot, target)): "ocr"}
    if provider.vision:
        tasks[asyncio.create_task(grid.find(provider, model, shot, target))] = "grid"
    results: dict[str, Optional[Found]] = {}
    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, timeout=SLOW_TIMEOUT_S,
                                               return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break
            for t in done:
                try:
                    results[tasks[t]] = t.result()
                except Exception:
                    log.debug("%s locator failed", tasks[t], exc_info=True)
                    results[tasks[t]] = None
            hit = results.get("ocr")
            if hit is not None and hit.score >= 0.9:
                return hit          # exact text on screen beats the grid's estimate
        return results.get("ocr") or results.get("grid")
    finally:
        for t in tasks:
            t.cancel()
