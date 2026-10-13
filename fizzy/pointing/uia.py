"""Find a control by name in the app's UI Automation tree. Exact and fast."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from fizzy.pointing.match import score

log = logging.getLogger(__name__)

MIN_SCORE = 0.74
MAX_NODES = 4000
TIME_BUDGET_S = 1.2

# Things people point at get a small boost over static text.
_INTERACTIVE = {
    "ButtonControl", "MenuItemControl", "TabItemControl", "HyperlinkControl", "ListItemControl",
    "CheckBoxControl", "RadioButtonControl", "ComboBoxControl", "EditControl", "SplitButtonControl",
    "TreeItemControl", "MenuBarControl",
}


@dataclass(frozen=True)
class Found:
    x: float                # physical pixels, centre of the control
    y: float
    label: str
    score: float
    source: str


def find(hwnd: int, target: str) -> Optional[Found]:
    """Blocking; run in a worker thread."""
    try:
        import uiautomation as auto
    except ImportError:
        return None
    best: Optional[Found] = None
    started = time.monotonic()
    seen = 0
    try:
        with auto.UIAutomationInitializerInThread(debug=False):
            root = auto.ControlFromHandle(hwnd)
            if root is None:
                return None
            for ctrl, _depth in auto.WalkControl(root, includeTop=False, maxDepth=30):
                seen += 1
                if seen > MAX_NODES or time.monotonic() - started > TIME_BUDGET_S:
                    break
                name = ctrl.Name
                if not name or len(name) > 120:
                    continue
                s = score(target, name)
                if ctrl.ControlTypeName in _INTERACTIVE:
                    s += 0.04
                if s < MIN_SCORE or (best and s <= best.score):
                    continue
                try:
                    if ctrl.IsOffscreen:
                        continue
                    r = ctrl.BoundingRectangle
                except Exception:
                    continue
                if r.width() <= 2 or r.height() <= 2:
                    continue
                best = Found((r.left + r.right) / 2, (r.top + r.bottom) / 2, name, s, "uia")
                if s >= 1.0:
                    break
    except Exception:
        log.debug("UIA search failed", exc_info=True)
    log.info("UIA: %s after %d nodes in %.2fs", best, seen, time.monotonic() - started)
    return best
