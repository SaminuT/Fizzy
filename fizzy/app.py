"""Fizzy's entry point."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

from fizzy import APP_NAME, __version__, logs, single_instance
from fizzy.ai import registry
from fizzy.ai.base import Provider
from fizzy.context.screen import ScreenLayout
from fizzy.context.selection_watch import SelectionWatcher
from fizzy.context.tracker import ForegroundTracker
from fizzy.hotkey import Hotkey
from fizzy.runtime import AsyncRunner
from fizzy.session import Session
from fizzy.speech.mic import Microphone
from fizzy.settings import (
    CONTEXT_MODES, CONTEXT_SCREEN, CONTEXT_SELECTION_ONLY, CONTEXT_SELECTION_OR_SCREEN, Settings,
)
from fizzy.ui.panel import Panel
from fizzy.ui.theme import app_icon
from fizzy.ui.tray import Tray

log = logging.getLogger("fizzy")

CONTEXT_LABELS = {
    CONTEXT_SCREEN: "Screenshot",
    CONTEXT_SELECTION_OR_SCREEN: "Highlighted text, else screenshot",
    CONTEXT_SELECTION_ONLY: "Highlighted text only",
}


class _Bridge(QObject):
    """Carries results from the background loop back to the GUI thread."""
    models_ready = pyqtSignal(str, list)    # provider id, [(id, title)]


class FizzyApp:
    def __init__(self, qt: QApplication):
        self.qt = qt
        self.settings = Settings.load()
        self.runner = AsyncRunner()
        self.bridge = _Bridge()
        self.tracker = ForegroundTracker()
        self.selection = SelectionWatcher()
        provider = registry.startup_provider(self.settings)
        self.mic = Microphone(self.settings.mic_device)
        self.session = Session(self.settings, self.runner, provider, self.tracker, self.mic)
        self.hotkey = Hotkey(self.settings.hotkey)

        self.panel = Panel()
        self.tray = Tray()
        self.tray.set_builder(self._build_menu)
        self._connect()

    def _connect(self) -> None:
        s, p = self.session, self.panel
        p.question_submitted.connect(lambda q: s.ask_text(q, p.selection_to_send() or None))
        self.selection.changed.connect(p.set_selection)
        p.stop_requested.connect(s.cancel)
        p.model_chosen.connect(self._on_model_chosen)
        s.state_changed.connect(p.set_state)
        s.answer_started.connect(p.start_answer)
        s.answer_chunk.connect(p.append_answer)
        s.answer_done.connect(p.set_answer)
        s.error.connect(p.show_error)
        s.notice.connect(p.set_status_note)
        s.level.connect(p.meter.set_level)
        self.hotkey.pressed.connect(s.start_listening)
        self.hotkey.released.connect(s.stop_listening)
        self.hotkey.escape.connect(lambda: s.cancel() if s.state != "idle" else None)
        self.tray.show_panel.connect(p.focus_input)
        self.tray.quit_requested.connect(self.quit)
        self.bridge.models_ready.connect(self._on_models_ready)

    # ── providers and models ────────────────────────────────────────────

    def switch_provider(self, pid: str) -> None:
        if pid == self.session.provider.id:
            return
        provider = registry.build(pid, self.settings)
        self.settings.provider = pid
        self.settings.save()
        self.session.set_provider(provider)
        self._show_provider(provider)
        self.tray.rebuild()
        if not provider.is_configured():
            self.panel.show_error(f"{provider.label} needs a key or sign-in. Use Tray → Keys and sign-in.")

    def _show_provider(self, provider: Provider) -> None:
        self.panel.set_provider(provider.label)
        models, fresh = registry.cached_models(provider.id)
        self._fill_models(provider, [(m.id, m.title) for m in models])
        if not fresh and provider.is_configured():
            self.runner.submit(self._fetch_models(provider))

    async def _fetch_models(self, provider: Provider) -> None:
        try:
            models = await registry.refresh_models(provider)
        except Exception as e:
            log.info("couldn't list %s models: %s", provider.id, e)
            return
        self.bridge.models_ready.emit(provider.id, [(m.id, m.title) for m in models])

    def _on_models_ready(self, pid: str, models: list) -> None:
        if pid == self.session.provider.id:
            self._fill_models(self.session.provider, models)

    def _fill_models(self, provider: Provider, models: list) -> None:
        current = self.settings.model_for(provider.id) or provider.default_model
        if not models and provider.default_model:
            models = [(provider.default_model, provider.default_model)]
        self.panel.set_models(models, current or None)

    # ── tray menu ───────────────────────────────────────────────────────

    def _build_menu(self, menu: QMenu) -> None:
        ai = menu.addMenu("AI")
        group = QActionGroup(ai)
        for e in registry.ENTRIES:
            provider_ready = e.local or e.build(self.settings).is_configured()
            label = e.label if provider_ready else f"{e.label}  (needs a key)"
            a = QAction(label, ai, checkable=True, checked=self.session.provider.id == e.id)
            a.triggered.connect(lambda _c, pid=e.id: self.switch_provider(pid))
            group.addAction(a)
            ai.addAction(a)
        ai.addSeparator()
        refresh = QAction("Refresh model list", ai)
        refresh.triggered.connect(lambda: self.runner.submit(self._fetch_models(self.session.provider)))
        ai.addAction(refresh)

        ctx = menu.addMenu("Screen context")
        group = QActionGroup(ctx)
        for mode in CONTEXT_MODES:
            a = QAction(CONTEXT_LABELS[mode], ctx, checkable=True, checked=self.settings.screen_context == mode)
            a.triggered.connect(lambda _c, m=mode: self._set_context_mode(m))
            group.addAction(a)
            ctx.addAction(a)
        ctx.addSeparator()
        self._toggle(ctx, "Capture all monitors", "all_monitors")
        self._toggle(ctx, "Copy-to-read fallback (uses the clipboard)", "clipboard_fallback")
        self._toggle(menu, "Privacy guard", "privacy_guard")

    def _toggle(self, menu: QMenu, label: str, field: str, after=None) -> QAction:
        a = QAction(label, menu, checkable=True, checked=bool(getattr(self.settings, field)))

        def flip(checked: bool) -> None:
            setattr(self.settings, field, checked)
            self.settings.save()
            if after:
                after(checked)

        a.toggled.connect(flip)
        menu.addAction(a)
        return a

    def _set_context_mode(self, mode: str) -> None:
        self.settings.screen_context = mode
        self.settings.save()
        self.selection.set_enabled(mode != CONTEXT_SCREEN)

    def _on_model_chosen(self, model: str) -> None:
        if model:
            self.settings.set_model(self.session.provider.id, model)
            self.settings.save()

    def start(self) -> None:
        ScreenLayout.refresh()
        self.qt.screenAdded.connect(lambda _s: ScreenLayout.refresh())
        self.qt.screenRemoved.connect(lambda _s: ScreenLayout.refresh())
        for s in self.qt.screens():
            s.geometryChanged.connect(lambda _g: ScreenLayout.refresh())
        self.tracker.start()
        self.selection.start(self.settings.screen_context != CONTEXT_SCREEN)
        try:
            self.hotkey.start()
        except Exception:
            log.exception("couldn't register the hotkey")
            self.tray.notify(APP_NAME, f"Couldn't register the hotkey {self.settings.hotkey}. "
                                       "Typing in the panel still works.")
        self._show_provider(self.session.provider)
        self.tray.show()
        self.panel.show_near_corner()
        log.info("ready (provider=%s)", self.session.provider.id)

    def quit(self) -> None:
        log.info("quitting")
        self.session.cancel()
        self.selection.stop()
        self.hotkey.stop()
        self.mic.close()
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
