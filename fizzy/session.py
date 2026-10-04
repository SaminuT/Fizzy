"""One conversation turn at a time: question in, answer out.

The Qt side calls ask_text() / cancel(). Everything slow runs on the
background asyncio loop, and results come back through Qt signals, which
are safe to emit from any thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from fizzy import intent, prompts
from fizzy.ai.base import Message, Provider, ProviderError, Request
from fizzy.context.gather import Context, compose_question, gather
from fizzy.context.tracker import ForegroundTracker
from fizzy.runtime import AsyncRunner
from fizzy.settings import Settings

log = logging.getLogger(__name__)

HISTORY_TURNS = 8   # question/answer pairs remembered per app


class Session(QObject):
    state_changed = pyqtSignal(str)
    answer_started = pyqtSignal(str)        # the question
    answer_chunk = pyqtSignal(str)
    answer_done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, settings: Settings, runner: AsyncRunner, provider: Provider,
                 tracker: ForegroundTracker):
        super().__init__()
        self.settings = settings
        self.runner = runner
        self.provider = provider
        self.tracker = tracker
        self.state = "idle"
        self._task: Optional[asyncio.Task] = None
        # Separate history per app, so a chat about Excel doesn't leak into VS Code.
        self._history: dict[str, list[Message]] = {}
        self.last_answer = ""
        self.last_context: Optional[Context] = None

    # ── called from the Qt thread ───────────────────────────────────────

    def ask_text(self, text: str, selection: Optional[str] = None) -> None:
        """A typed question. selection is the highlighted text to include, if any."""
        win = self.tracker.current()
        self.runner.submit(self._start(self._turn(text, win, selection)), on_error=self._report)

    def cancel(self) -> None:
        self.runner.loop.call_soon_threadsafe(self._cancel_now)

    def set_provider(self, provider: Provider) -> None:
        old = self.provider
        self.provider = provider
        self.runner.submit(old.aclose())

    # ── loop side ───────────────────────────────────────────────────────

    async def _start(self, coro) -> None:
        """Run coro as the current turn, replacing any turn in progress."""
        self._cancel_now()
        task = asyncio.create_task(coro)
        self._task = task
        try:
            await task
        except asyncio.CancelledError:
            pass        # replaced by a newer turn, or the user pressed stop
        finally:
            # A newer turn owns the state now; only the latest turn resets it.
            if self._task is task:
                self._set_state("idle")

    def _cancel_now(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _turn(self, question: str, win, selection: Optional[str]) -> None:
        self._set_state("thinking")
        self.answer_started.emit(question)
        ctx = await gather(self.settings, win, vision=self.provider.vision, selection=selection,
                           pointing=intent.wants_pointing(question))
        self.last_context = ctx
        req = Request(
            system=prompts.system_prompt(ctx.lines),
            text=compose_question(question, ctx.selection),
            history=list(self._history.get(win.app_key, [])),
            images=ctx.images,
            model=self.settings.model_for(self.provider.id),
        )
        answer = await self._stream(req)
        self._remember(win.app_key, question, answer)
        self.answer_done.emit(answer)

    async def _stream(self, req: Request) -> str:
        parts: list[str] = []
        try:
            async for chunk in self.provider.stream(req):
                parts.append(chunk)
                self.answer_chunk.emit(chunk)
        except ProviderError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("%s request failed", self.provider.id)
            raise ProviderError(f"{self.provider.label} request failed: {e}") from e
        answer = "".join(parts).strip()
        if not answer:
            raise ProviderError(f"{self.provider.label} sent back an empty answer. Try again or pick another model.")
        return answer

    def _remember(self, app_key: str, question: str, answer: str) -> None:
        self.last_answer = answer
        h = self._history.setdefault(app_key, [])
        h += [Message("user", question), Message("assistant", answer)]
        del h[:-HISTORY_TURNS * 2]

    def forget(self) -> None:
        self._history.clear()

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _report(self, exc: BaseException) -> None:
        self.error.emit(str(exc))
        self._set_state("idle")
