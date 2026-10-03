"""Screenshots, and the maths between the three coordinate spaces Fizzy uses.

  physical  real device pixels, as mss and Win32 (GetCursorPos, UI Automation)
            report them for a per-monitor DPI-aware process.
  logical   Qt's device-independent pixels, which the overlay draws in.
  image     pixels of the downscaled JPEG the model sees. Models are asked
            to answer in a 0–1000 grid over the image ("norm"), so the exact
            encoded size never matters to them.

Qt objects may only be touched on the GUI thread, so the monitor layout is
read there (ScreenLayout.refresh) and cached for the capture code, which runs
on the background loop.
"""

from __future__ import annotations

import base64
import ctypes
import io
import threading
from dataclasses import dataclass
from typing import Optional

from fizzy.ai.base import Image

MAX_IMAGE_WIDTH = 1440
JPEG_QUALITY = 80
NORM = 1000


@dataclass(frozen=True)
class Monitor:
    index: int                      # 1-based, in mss order
    left: int                       # physical rect
    top: int
    width: int
    height: int
    logical_left: float             # Qt geometry of the same screen
    logical_top: float
    scale: float                    # physical px per logical px

    def contains(self, px: float, py: float) -> bool:
        return self.left <= px < self.left + self.width and self.top <= py < self.top + self.height

    def to_logical(self, px: float, py: float) -> tuple[float, float]:
        return (self.logical_left + (px - self.left) / self.scale,
                self.logical_top + (py - self.top) / self.scale)

    def to_physical(self, lx: float, ly: float) -> tuple[float, float]:
        return (self.left + (lx - self.logical_left) * self.scale,
                self.top + (ly - self.logical_top) * self.scale)


@dataclass
class Shot:
    monitor: Monitor
    image: Image
    pil: object                     # PIL.Image at the encoded size (for OCR / grids)

    @property
    def ratio(self) -> float:
        """Encoded pixels per physical pixel."""
        return self.image.width / self.monitor.width

    def norm_to_physical(self, nx: float, ny: float) -> tuple[float, float]:
        m = self.monitor
        return (m.left + nx / NORM * m.width, m.top + ny / NORM * m.height)

    def physical_to_norm(self, px: float, py: float) -> tuple[int, int]:
        m = self.monitor
        return (round((px - m.left) / m.width * NORM), round((py - m.top) / m.height * NORM))

    def image_to_physical(self, ix: float, iy: float) -> tuple[float, float]:
        return (self.monitor.left + ix / self.ratio, self.monitor.top + iy / self.ratio)


class ScreenLayout:
    """Cached list of monitors; refresh() must run on the Qt GUI thread."""

    _lock = threading.Lock()
    _monitors: list[Monitor] = []

    @classmethod
    def refresh(cls) -> list[Monitor]:
        import mss
        from PyQt6.QtGui import QGuiApplication

        with mss.mss() as sct:
            physical = [(m["left"], m["top"], m["width"], m["height"]) for m in sct.monitors[1:]]
        screens = [(s.geometry(), s.devicePixelRatio()) for s in QGuiApplication.screens()]
        monitors = match_screens(physical, [((g.x(), g.y(), g.width(), g.height()), f) for g, f in screens])
        with cls._lock:
            cls._monitors = monitors
        return monitors

    @classmethod
    def monitors(cls) -> list[Monitor]:
        with cls._lock:
            return list(cls._monitors)


def match_screens(
    physical: list[tuple[int, int, int, int]],
    logical: list[tuple[tuple[int, int, int, int], float]],
) -> list[Monitor]:
    """Pair each physical monitor rect with the Qt screen that shows it.

    Qt reports logical geometry plus a scale factor. A screen's physical size
    is its logical size times the factor; its origin is either kept as-is or
    scaled, depending on the Qt version, so both candidates are tried.
    """
    remaining = list(logical)
    out: list[Monitor] = []
    for i, (left, top, w, h) in enumerate(physical, start=1):
        best = None
        for cand in remaining:
            (lx, ly, lw, lh), f = cand
            same_size = abs(lw * f - w) <= 2 and abs(lh * f - h) <= 2
            if not same_size:
                continue
            origin_match = (lx, ly) == (left, top) or (abs(lx * f - left) <= 2 and abs(ly * f - top) <= 2)
            if origin_match:
                best = cand
                break
            best = best or cand
        if best is None:
            # No Qt screen of that size (layout changing?) — assume no scaling.
            out.append(Monitor(i, left, top, w, h, float(left), float(top), 1.0))
            continue
        remaining.remove(best)
        (lx, ly, _lw, _lh), f = best
        out.append(Monitor(i, left, top, w, h, float(lx), float(ly), float(f) or 1.0))
    return out


# ── pointer ─────────────────────────────────────────────────────────────

class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def pointer_physical() -> Optional[tuple[int, int]]:
    pt = _POINT()
    try:
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
    except AttributeError:
        pass
    return None


def monitor_at(px: float, py: float, monitors: list[Monitor]) -> Optional[Monitor]:
    for m in monitors:
        if m.contains(px, py):
            return m
    return None


def pointer_monitor(monitors: list[Monitor]) -> Optional[Monitor]:
    pos = pointer_physical()
    if pos is None:
        return monitors[0] if monitors else None
    return monitor_at(*pos, monitors) or (monitors[0] if monitors else None)


# ── capture ─────────────────────────────────────────────────────────────

def capture(monitors: list[Monitor]) -> list[Shot]:
    """Grab and encode each monitor. Blocking; run it in a worker thread."""
    import mss
    from PIL import Image as PILImage

    shots: list[Shot] = []
    with mss.mss() as sct:
        for m in monitors:
            raw = sct.grab({"left": m.left, "top": m.top, "width": m.width, "height": m.height})
            img = PILImage.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            if img.width > MAX_IMAGE_WIDTH:
                h = round(img.height * MAX_IMAGE_WIDTH / img.width)
                img = img.resize((MAX_IMAGE_WIDTH, h), PILImage.Resampling.LANCZOS)
            shots.append(Shot(m, encode_jpeg(img), img))
    return shots


def encode_jpeg(img) -> Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return Image(base64.b64encode(buf.getvalue()).decode("ascii"), img.width, img.height)
