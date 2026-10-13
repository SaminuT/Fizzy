"""Find text on the screenshot with on-device OCR, for apps that draw their own UI."""

from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

from fizzy.context.screen import Shot
from fizzy.pointing.match import normalise, score
from fizzy.pointing.uia import Found

log = logging.getLogger(__name__)

MIN_SCORE = 0.78
_engine = None
_engine_lock = threading.Lock()


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _ocr():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        return _engine


def find(shot: Shot, target: str) -> Optional[Found]:
    """Blocking; run in a worker thread."""
    if not available():
        return None
    try:
        result, _elapsed = _ocr()(np.asarray(shot.pil))
    except Exception:
        log.debug("OCR failed", exc_info=True)
        return None
    best: Optional[Found] = None
    want = normalise(target)
    for box, text, conf in result or []:
        s = score(target, text)
        if s < MIN_SCORE or float(conf) < 0.5:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        left, right = min(xs), max(xs)
        cx = (left + right) / 2
        # When the target is part of a longer line, aim at that part of the line.
        line = normalise(text)
        at = line.find(want) if want else -1
        if at >= 0 and len(line) > len(want):
            frac = (at + len(want) / 2) / len(line)
            cx = left + (right - left) * frac
        cy = (min(ys) + max(ys)) / 2
        px, py = shot.image_to_physical(cx, cy)
        if best is None or s > best.score:
            best = Found(px, py, text, s, "ocr")
    log.info("OCR: %s", best)
    return best
