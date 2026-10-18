"""The floating panel: status, the answer as it streams in, and the typing box."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from fizzy import APP_NAME
from fizzy.ui import theme, win32
from fizzy.ui.theme import css

STATE_TEXT = {
    "idle": "Ready",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
}


class LevelMeter(QWidget):
    """A thin bar that follows the mic level."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 3)
        self._level = 0.0
        self._decay = QTimer(self, interval=50)
        self._decay.timeout.connect(self._fade)

    def set_level(self, rms: float) -> None:
        self._level = max(self._level, min(1.0, rms * 12))
        if not self._decay.isActive():
            self._decay.start()
        self.update()

    def _fade(self) -> None:
        self._level *= 0.8
        if self._level < 0.02:
            self._level = 0.0
            self._decay.stop()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), theme.BORDER)
        p.fillRect(QRectF(0, 0, self.width() * self._level, self.height()), theme.TEXT_DIM)


class Panel(QWidget):
    question_submitted = pyqtSignal(str)
    model_chosen = pyqtSignal(str)
    stop_requested = pyqtSignal()
    speak_toggled = pyqtSignal(bool)

    WIDTH = 380
    HEIGHT = 420

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME)
        self.resize(self.WIDTH, self.HEIGHT)
        self._drag_from: QPoint | None = None
        self._answer = ""
        self._render_timer = QTimer(self, singleShot=True, interval=60)
        self._render_timer.timeout.connect(self._render_answer)
        self._build()
        self.set_state("idle")

    # ── layout ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setStyleSheet(
            f"QLabel {{ color:{css(theme.TEXT_DIM)}; font-size:12px; }}"
            f"QPushButton {{ background:transparent; color:{css(theme.TEXT_DIM)}; border:none; font-size:12px; padding:2px 4px; }}"
            f"QPushButton:hover {{ color:{css(theme.TEXT)}; }}"
            f"QLineEdit, QComboBox {{ background:{css(theme.SURFACE)}; color:{css(theme.TEXT)};"
            f" border:1px solid {css(theme.BORDER)}; border-radius:4px; padding:6px 8px; font-size:13px; }}"
            f"QLineEdit:focus {{ border-color:{css(theme.TEXT_DIM)}; }}"
            "QComboBox { padding:2px 6px; font-size:12px; }"
            f"QTextBrowser {{ background:transparent; border:none; color:{css(theme.TEXT)}; font-size:13px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 10, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.status = QLabel("")
        header.addWidget(self.status)
        self.meter = LevelMeter()
        self.meter.hide()
        header.addWidget(self.meter, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        self.speak_btn = QPushButton()
        self.speak_btn.setCheckable(True)
        self.speak_btn.toggled.connect(self._on_speak_toggled)
        header.addWidget(self.speak_btn)
        hide = QPushButton("×")
        hide.setToolTip("Hide (reopen from the tray)")
        hide.setStyleSheet("font-size:16px;")
        hide.clicked.connect(self.hide)
        header.addWidget(hide)
        root.addLayout(header)

        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(True)
        self.answer.setPlaceholderText("Ask about anything on your screen.")
        root.addWidget(self.answer, stretch=1)

        self.extra_rows = QVBoxLayout()
        self.extra_rows.setSpacing(6)
        root.addLayout(self.extra_rows)

        # "Using highlighted text" line, shown while a selection is on offer.
        self.chip = QWidget()
        chip = QHBoxLayout(self.chip)
        chip.setContentsMargins(0, 0, 0, 0)
        self.chip_label = QLabel("")
        chip.addWidget(self.chip_label, stretch=1)
        drop = QPushButton("×")
        drop.setToolTip("Don't send the highlighted text")
        drop.clicked.connect(self._drop_selection)
        chip.addWidget(drop)
        self.chip.hide()
        self.extra_rows.addWidget(self.chip)
        self._selection = ""
        self._selection_dropped = False

        ask = QHBoxLayout()
        ask.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask something")
        self.input.returnPressed.connect(self._submit)
        ask.addWidget(self.input, stretch=1)
        self.send = QPushButton("Send")
        self.send.clicked.connect(self._on_send_clicked)
        ask.addWidget(self.send)
        root.addLayout(ask)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.badge = QLabel("")
        footer.addWidget(self.badge)
        self.models = QComboBox()
        self.models.activated.connect(lambda _i: self.model_chosen.emit(self.models.currentData() or ""))
        footer.addWidget(self.models, stretch=1)
        root.addLayout(footer)

    # ── public API ──────────────────────────────────────────────────────

    def set_provider(self, label: str) -> None:
        self.badge.setText(label)

    def set_models(self, models: list[tuple[str, str]], current: str | None) -> None:
        """models: [(id, title)]"""
        self.models.blockSignals(True)
        self.models.clear()
        for mid, title in models:
            self.models.addItem(title, mid)
        if current:
            i = self.models.findData(current)
            if i < 0:
                self.models.insertItem(0, current, current)
                i = 0
            self.models.setCurrentIndex(i)
        self.models.blockSignals(False)

    def set_speaking_mode(self, on: bool) -> None:
        self.speak_btn.blockSignals(True)
        self.speak_btn.setChecked(on)
        self.speak_btn.blockSignals(False)
        self._show_speak(on)

    def _on_speak_toggled(self, on: bool) -> None:
        self._show_speak(on)
        self.speak_toggled.emit(on)

    def _show_speak(self, on: bool) -> None:
        self.speak_btn.setText("Sound on" if on else "Muted")
        self.speak_btn.setToolTip("Speaking mode is on (click to mute)" if on
                                  else "Speaking mode is off (click to hear answers)")

    def set_state(self, state: str) -> None:
        self._state = state
        self.status.setText(STATE_TEXT.get(state, state))
        self.meter.setVisible(state == "listening")
        busy = state in ("thinking", "speaking")
        self.send.setText("Stop" if busy else "Send")

    def set_selection(self, text: str) -> None:
        """Offer (or withdraw) the highlighted text from the user's app."""
        if text != self._selection:
            self._selection_dropped = False
        self._selection = text
        if text and not self._selection_dropped:
            preview = " ".join(text.split())
            if len(preview) > 70:
                preview = preview[:70] + "…"
            self.chip_label.setText(f"Using highlighted text: “{preview}”")
            self.chip.show()
        else:
            self.chip.hide()

    def selection_to_send(self) -> str:
        return "" if self._selection_dropped else self._selection

    def _drop_selection(self) -> None:
        self._selection_dropped = True
        self.chip.hide()

    def set_status_note(self, text: str) -> None:
        self.status.setText(text)

    def start_answer(self, question: str = "") -> None:
        self._question = question
        self._answer = ""
        self._render_answer()

    def append_answer(self, chunk: str) -> None:
        self._answer += chunk
        if not self._render_timer.isActive():
            self._render_timer.start()

    def set_answer(self, text: str) -> None:
        self._answer = text
        self._render_answer()

    def show_error(self, message: str) -> None:
        self.answer.setHtml(f"<p style='color:{css(theme.RED)}'>{_escape(message)}</p>")

    def show_near_corner(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if not self.isVisible():
            self.move(screen.right() - self.width() - 20, screen.bottom() - self.height() - 20)
        self.show()
        self.raise_()

    def focus_input(self) -> None:
        self.show_near_corner()
        win32.bring_to_front(self)
        self.activateWindow()
        self.input.setFocus()
        self.input.selectAll()

    def toggle(self) -> None:
        """Show the panel ready to type, or hide it if it's already in use."""
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.focus_input()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape and self._state == "idle":
            self.hide()         # Esc in an idle panel closes it
        else:
            super().keyPressEvent(e)

    # ── internals ───────────────────────────────────────────────────────

    def _render_answer(self) -> None:
        q = getattr(self, "_question", "")
        md = f"**You:** {q}\n\n{self._answer}" if q else self._answer
        self.answer.setMarkdown(md)
        bar = self.answer.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.question_submitted.emit(text)

    def _on_send_clicked(self) -> None:
        if self._state in ("thinking", "speaking"):
            self.stop_requested.emit()
        else:
            self._submit()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        win32.exclude_from_capture(self)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.fillPath(path, theme.BG)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawPath(path)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 36:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from is not None:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag_from = None


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

