"""Fizzy's entry point."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from fizzy import APP_NAME, __version__, logs, single_instance
from fizzy.ai.anthropic_provider import AnthropicProvider
from fizzy.runtime import AsyncRunner
from fizzy.session import Session
from fizzy.settings import Settings
from fizzy.ui.panel import Panel
from fizzy.ui.theme import app_icon
from fizzy.ui.tray import Tray

log = logging.getLogger("fizzy")


class FizzyApp:
    def __init__(self, qt: QApplication):
        self.qt = qt
        self.settings = Settings.load()
        self.runner = AsyncRunner()
        provider = AnthropicProvider()
        self.session = Session(self.settings, self.runner, provider)

        self.panel = Panel()
        self.panel.set_provider(provider.label)
        self.panel.set_models([(provider.default_model, provider.default_model)],
                              self.settings.model_for(provider.id) or provider.default_model)
        self.tray = Tray()
        self._connect()

    def _connect(self) -> None:
        s, p = self.session, self.panel
        p.question_submitted.connect(s.ask_text)
        p.stop_requested.connect(s.cancel)
        p.model_chosen.connect(self._on_model_chosen)
        s.state_changed.connect(p.set_state)
        s.answer_started.connect(p.start_answer)
        s.answer_chunk.connect(p.append_answer)
        s.answer_done.connect(p.set_answer)
        s.error.connect(p.show_error)
        self.tray.show_panel.connect(p.focus_input)
        self.tray.quit_requested.connect(self.quit)

    def _on_model_chosen(self, model: str) -> None:
        if model:
            self.settings.set_model(self.session.provider.id, model)
            self.settings.save()

    def start(self) -> None:
        self.tray.show()
        self.panel.show_near_corner()
        log.info("ready (provider=%s)", self.session.provider.id)

    def quit(self) -> None:
        log.info("quitting")
        self.session.cancel()
        try:
            self.runner.run(self.session.provider.aclose(), timeout=3)
        except Exception:
            log.debug("closing provider failed", exc_info=True)
        self.runner.stop()
        self.tray.icon.hide()
        self.qt.quit()


def main() -> int:
    logs.setup()
    log.info("%s %s starting", APP_NAME, __version__)
    qt = QApplication(sys.argv)
    qt.setApplicationName(APP_NAME)
    qt.setWindowIcon(app_icon())
    qt.setQuitOnLastWindowClosed(False)

    if not single_instance.acquire():
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running. Look for it in the system tray.")
        return 0

    app = FizzyApp(qt)
    app.start()
    return qt.exec()
