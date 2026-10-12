"""The buddy: a small Fizzy orb that rides beside the pointer.

There's one transparent, click-through overlay window per monitor. The
Buddy controller owns the orb's position (global logical pixels), animates
it, and asks only the overlay under it to repaint the area that changed.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from fizzy.ui import theme, win32

ORB_RADIUS = 9.0
OFFSET = QPointF(24, 22)        # orb sits below-right of the pointer tip
FPS = 60
FOLLOW_EASE = 0.32


@dataclass
class _Flight:
    start: QPointF
    control: QPointF
    end: QPointF
    began: float
    duration: float

    def at(self, now: float) -> tuple[QPointF, bool]:
        t = min(1.0, (now - self.began) / self.duration)
        e = t * t * (3 - 2 * t)         # smoothstep
        a, c, b = self.start, self.control, self.end
        u = 1 - e
        p = a * (u * u) + c * (2 * u * e) + b * (e * e)
        return p, t >= 1.0


def _arc(start: QPointF, end: QPointF) -> tuple[QPointF, float]:
    """Control point for a gentle upward arc, and a duration that grows with distance."""
    mid = (start + end) / 2
    d = math.hypot(end.x() - start.x(), end.y() - start.y())
    lift = min(140.0, d * 0.25)
    return QPointF(mid.x(), mid.y() - lift), max(0.35, min(0.95, d / 1400))


class Overlay(QWidget):
    def __init__(self, screen, buddy: "Buddy"):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.buddy = buddy
        self.screen_ref = screen
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def showEvent(self, e) -> None:
        super().showEvent(e)
        win32.exclude_from_capture(self)
        win32.no_activate(self)

    def origin(self) -> QPointF:
        return QPointF(self.screen_ref.geometry().topLeft())

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-self.origin())
        self.buddy.paint(p)


class Buddy(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.pos = QPointF(QCursor.pos()) + OFFSET
        self._flight: Optional[_Flight] = None
        self._target: Optional[QPointF] = None      # what we're pointing at
        self._label = ""
        self._dwell_since = 0.0
        self._returning = False
        self._last_rect = QRectF()
        self._overlays: list[Overlay] = []
        self._timer = QTimer(self, interval=int(1000 / FPS))
        self._timer.timeout.connect(self._tick)
        self.visible = True

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        self._rebuild_overlays()
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda _s: self._rebuild_overlays())
        app.screenRemoved.connect(lambda _s: self._rebuild_overlays())
        self._timer.start()

    def _rebuild_overlays(self) -> None:
        for o in self._overlays:
            o.close()
            o.deleteLater()
        self._overlays = [Overlay(s, self) for s in QGuiApplication.screens()]
        for o in self._overlays:
            o.setGeometry(o.screen_ref.geometry())
            o.screen_ref.geometryChanged.connect(lambda g, ov=o: ov.setGeometry(g))
            if self.visible:
                o.show()

    def set_visible(self, visible: bool) -> None:
        self.visible = visible
        for o in self._overlays:
            o.setVisible(visible)

    def stop(self) -> None:
        self._timer.stop()
        for o in self._overlays:
            o.close()

    # ── public API ──────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        self.state = state

    def point_at(self, target: QPointF, label: str = "") -> None:
        """Glide over to a spot (global logical px) and stay there until release()."""
        self._target = QPointF(target)
        self._label = label
        self._returning = False
        end = self._target + QPointF(14, 14)
        control, duration = _arc(self.pos, end)
        self._flight = _Flight(QPointF(self.pos), control, end, time.monotonic(), duration)

    def release(self) -> None:
        """Stop pointing and fly back to the pointer."""
        if self._target is None and self._flight is None:
            return
        self._target = None
        self._label = ""
        self._returning = True
        end = QPointF(QCursor.pos()) + OFFSET
        control, duration = _arc(self.pos, end)
        self._flight = _Flight(QPointF(self.pos), control, end, time.monotonic(), duration)

    @property
    def pointing(self) -> bool:
        return self._target is not None

    # ── animation ───────────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self.visible:
            return
        now = time.monotonic()
        if self._flight is not None:
            if self._returning:
                # Keep aiming at the pointer, which may have moved meanwhile.
                self._flight.end = QPointF(QCursor.pos()) + OFFSET
            self.pos, done = self._flight.at(now)
            if done:
                self._flight = None
                if self._target is not None:
                    self._dwell_since = now
                self._returning = False
        elif self._target is None:
            goal = QPointF(QCursor.pos()) + OFFSET
            self.pos += (goal - self.pos) * FOLLOW_EASE
        self._repaint()

    def _bounds(self) -> QRectF:
        r = ORB_RADIUS * 3.2
        rect = QRectF(self.pos.x() - r, self.pos.y() - r, 2 * r, 2 * r)
        if self._target is not None:
            t = self._target
            rect = rect.united(QRectF(t.x() - 40, t.y() - 40, 80, 80))
            if self._label:
                rect = rect.united(self._label_rect())
        return rect.adjusted(-4, -4, 4, 4)

    def _repaint(self) -> None:
        rect = self._bounds()
        dirty = rect.united(self._last_rect)
        self._last_rect = rect
        for o in self._overlays:
            local = dirty.translated(-o.origin())
            area = QRectF(o.rect())
            if local.intersects(area):
                o.update(local.toAlignedRect().intersected(QRect(o.rect())))

    # ── drawing ─────────────────────────────────────────────────────────

    def paint(self, p: QPainter) -> None:
        now = time.monotonic()
        accent = theme.STATE_COLOURS.get(self.state, theme.VIOLET)
        if self._target is not None and self._flight is None:
            self._paint_target(p, now, accent)

        radius = ORB_RADIUS
        if self.state == "speaking":
            radius *= 1.0 + 0.12 * abs(math.sin(now * 9))
        elif self.state == "idle":
            radius *= 1.0 + 0.04 * math.sin(now * 2)

        if self.state == "listening":
            ring = (now * 1.4) % 1.0
            c = QColor(accent)
            c.setAlphaF(0.6 * (1 - ring))
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(self.pos, radius + 4 + ring * 12, radius + 4 + ring * 12)

        theme.paint_orb(p, self.pos, radius, accent if self.state != "idle" else None)

        if self.state == "thinking":
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                a = now * 4 + i * (2 * math.pi / 3)
                dot = self.pos + QPointF(math.cos(a), math.sin(a)) * (radius + 7)
                p.setBrush(QColor(255, 255, 255, 220))
                p.drawEllipse(dot, 2.2, 2.2)

    def _paint_target(self, p: QPainter, now: float, accent: QColor) -> None:
        t = self._target
        pulse = (now - self._dwell_since) * 1.6 % 1.0
        c = QColor(accent)
        c.setAlphaF(0.85 * (1 - pulse))
        p.setPen(QPen(c, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(t, 10 + pulse * 22, 10 + pulse * 22)
        p.setPen(QPen(QColor(accent), 2))
        p.drawEllipse(t, 9, 9)
        # A short stroke from the orb to the spot it's pointing at.
        p.drawLine(self.pos + QPointF(-ORB_RADIUS * 0.6, -ORB_RADIUS * 0.6), t + QPointF(6, 6))
        if self._label:
            r = self._label_rect()
            path = QPainterPath()
            path.addRoundedRect(r, 9, 9)
            p.fillPath(path, theme.BG)
            p.setPen(QPen(accent, 1.2))
            p.drawPath(path)
            p.setPen(theme.TEXT)
            p.setFont(self._font())
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._label)

    @staticmethod
    def _font() -> QFont:
        f = QFont("Segoe UI", 10)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _label_rect(self) -> QRectF:
        fm = QFontMetricsF(self._font())
        w = min(320.0, fm.horizontalAdvance(self._label) + 22)
        h = fm.height() + 10
        t = self._target
        above = t.y() - 34 - h
        top = above if above > 8 else t.y() + 34       # flip below near the top edge
        return QRectF(t.x() - w / 2, top, w, h)
