"""The floating panel: status, the answer as it streams in, and the typing box."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from fizzy import APP_NAME
from fizzy.ui import theme
from fizzy.ui.theme import css

STATE_TEXT = {
    "idle": "Ready",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
}


class Panel(QWidget):
    question_submitted = pyqtSignal(str)
    model_chosen = pyqtSignal(str)
    stop_requested = pyqtSignal()

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
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setStyleSheet(f"color:{css(theme.TEXT)}; font-size:16px; font-weight:600;")
        header.addWidget(title)
        self.badge = QLabel("")
        self.badge.setStyleSheet(
            f"color:{css(theme.TEXT)}; background:{css(theme.SURFACE)}; border:1px solid {css(theme.BORDER)};"
            "border-radius:9px; padding:1px 8px; font-size:11px;")
        header.addWidget(self.badge)
        header.addStretch()
        hide = QPushButton("✕")
        hide.setFixedSize(24, 24)
        hide.setToolTip("Hide (reopen from the tray)")
        hide.setStyleSheet(self._flat_button_css())
        hide.clicked.connect(self.hide)
        header.addWidget(hide)
        root.addLayout(header)

        status = QHBoxLayout()
        status.setSpacing(6)
        self.dot = QLabel("●")
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{css(theme.TEXT_DIM)}; font-size:12px;")
        status.addWidget(self.dot)
        status.addWidget(self.status)
        status.addStretch()
        self.status_row = status
        root.addLayout(status)

        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(True)
        self.answer.setStyleSheet(
            f"QTextBrowser {{ background:transparent; border:none; color:{css(theme.TEXT)}; font-size:13px; }}")
        self.answer.setPlaceholderText("Ask me anything about what's on your screen.")
        root.addWidget(self.answer, stretch=1)

        self.extra_rows = QVBoxLayout()
        self.extra_rows.setSpacing(6)
        root.addLayout(self.extra_rows)

        ask = QHBoxLayout()
        ask.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a question and press Enter")
        self.input.setStyleSheet(
            f"QLineEdit {{ background:{css(theme.SURFACE)}; color:{css(theme.TEXT)};"
            f" border:1px solid {css(theme.BORDER)}; border-radius:10px; padding:7px 10px; font-size:13px; }}"
            f"QLineEdit:focus {{ border-color:{css(theme.VIOLET)}; }}")
        self.input.returnPressed.connect(self._submit)
        ask.addWidget(self.input, stretch=1)
        self.send = QPushButton("➤")
        self.send.setFixedSize(34, 34)
        self.send.setToolTip("Send")
        self.send.setStyleSheet(
            f"QPushButton {{ background:{css(theme.VIOLET)}; color:white; border:none; border-radius:10px; font-size:14px; }}"
            f"QPushButton:hover {{ background:{css(theme.VIOLET.lighter(115))}; }}"
            "QPushButton:disabled { background:rgba(124,92,255,90); }")
        self.send.clicked.connect(self._on_send_clicked)
        ask.addWidget(self.send)
        root.addLayout(ask)

        footer = QHBoxLayout()
        lbl = QLabel("Model")
        lbl.setStyleSheet(f"color:{css(theme.TEXT_DIM)}; font-size:11px;")
        footer.addWidget(lbl)
        self.models = QComboBox()
        self.models.setStyleSheet(
            f"QComboBox {{ background:{css(theme.SURFACE)}; color:{css(theme.TEXT)}; border:1px solid {css(theme.BORDER)};"
            " border-radius:6px; padding:2px 6px; font-size:11px; }")
        self.models.activated.connect(lambda _i: self.model_chosen.emit(self.models.currentData() or ""))
        footer.addWidget(self.models, stretch=1)
        root.addLayout(footer)

    @staticmethod
    def _flat_button_css() -> str:
        return (f"QPushButton {{ background:{css(theme.SURFACE)}; color:{css(theme.TEXT_DIM)}; border:none;"
                " border-radius:12px; font-size:11px; }"
                f"QPushButton:hover {{ color:{css(theme.TEXT)}; }}")

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

    def set_state(self, state: str) -> None:
        self._state = state
        colour = theme.STATE_COLOURS.get(state, theme.VIOLET)
        self.dot.setStyleSheet(f"color:{css(colour)}; font-size:10px;")
        self.status.setText(STATE_TEXT.get(state, state))
        busy = state in ("thinking", "speaking")
        self.send.setText("■" if busy else "➤")
        self.send.setToolTip("Stop" if busy else "Send")

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
        self.answer.setHtml(f"<p style='color:{css(theme.CORAL)}'>{_escape(message)}</p>")

    def show_near_corner(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if not self.isVisible():
            self.move(screen.right() - self.width() - 20, screen.bottom() - self.height() - 20)
        self.show()
        self.raise_()

    def focus_input(self) -> None:
        self.show_near_corner()
        self.activateWindow()
        self.input.setFocus()

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

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, 16)
        p.fillPath(path, theme.BG)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawPath(path)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 44:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from is not None:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag_from = None


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

