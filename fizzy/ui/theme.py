"""Fizzy's colours, fonts, and the orb artwork used for the tray icon and buddy."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap, QRadialGradient

# Brand: a violet-to-pink "fizz" orb.
VIOLET = QColor(124, 92, 255)
PINK = QColor(255, 94, 168)
MINT = QColor(64, 220, 180)
AMBER = QColor(255, 184, 64)
CORAL = QColor(255, 99, 99)

BG = QColor(22, 20, 30, 236)
SURFACE = QColor(36, 33, 48)
BORDER = QColor(70, 64, 92)
TEXT = QColor(236, 232, 248)
TEXT_DIM = QColor(150, 144, 172)

# State → accent colour, shared by the panel's status dot and the buddy.
STATE_COLOURS = {
    "idle": VIOLET,
    "listening": CORAL,
    "thinking": AMBER,
    "speaking": MINT,
}


def css(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


def paint_orb(p: QPainter, centre: QPointF, radius: float, accent: QColor | None = None) -> None:
    """A glossy sphere with three small rising bubbles."""
    top = accent or VIOLET
    g = QRadialGradient(centre + QPointF(-radius * 0.35, -radius * 0.4), radius * 1.4)
    g.setColorAt(0.0, top.lighter(150))
    g.setColorAt(0.55, top)
    g.setColorAt(1.0, PINK)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(centre, radius, radius)

    # Highlight
    p.setBrush(QColor(255, 255, 255, 150))
    p.drawEllipse(centre + QPointF(-radius * 0.38, -radius * 0.42), radius * 0.22, radius * 0.14)

    # Bubbles
    p.setBrush(QColor(255, 255, 255, 190))
    for dx, dy, r in ((0.2, -0.05, 0.12), (0.42, 0.25, 0.08), (0.05, 0.38, 0.06)):
        p.drawEllipse(centre + QPointF(radius * dx, radius * dy), radius * r, radius * r)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = size / 2 - max(1.0, size / 32)
        paint_orb(p, QRectF(0, 0, size, size).center(), r)
        p.end()
        icon.addPixmap(pm)
    return icon
