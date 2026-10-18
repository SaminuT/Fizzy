"""Fizzy's colours and the plain dot used for the app icon and the buddy."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

# Neutral greys, one red for "the mic is on".
BG = QColor(30, 30, 30)
SURFACE = QColor(42, 42, 42)
BORDER = QColor(58, 58, 58)
TEXT = QColor(230, 230, 230)
TEXT_DIM = QColor(150, 150, 150)
DOT = QColor(128, 128, 128)
OUTLINE = QColor(0, 0, 0, 70)
RED = QColor(229, 72, 77)


def css(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


def paint_dot(p: QPainter, centre: QPointF, radius: float, fill: QColor = DOT) -> None:
    """A mid-grey filled circle with a faint edge, so it reads as solid on light and dark backgrounds."""
    p.setPen(QPen(OUTLINE, 1))
    p.setBrush(fill)
    p.drawEllipse(centre, radius, radius)


def paint_icon(p: QPainter, size: int) -> None:
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_dot(p, QRectF(0, 0, size, size).center(), size / 2 - max(1.0, size / 16))


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        paint_icon(p, size)
        p.end()
        icon.addPixmap(pm)
    return icon
