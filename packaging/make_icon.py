"""Render Fizzy's orb to a multi-size .ico for the exe and installer.

Usage: python packaging/make_icon.py build/fizzy.ico
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter

from fizzy.ui.theme import paint_orb

SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def render(size: int) -> Image.Image:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_orb(p, QPointF(size / 2, size / 2), size / 2 - max(1.0, size / 32))
    p.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data())))


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/fizzy.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    _app = QGuiApplication(["make_icon", "-platform", "offscreen"])
    render(256).save(out, format="ICO", sizes=SIZES)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
