"""One conversation turn at a time: question in, answer out.

The Qt side calls ask_text() / cancel(). Everything slow runs on the
background asyncio loop, and results come back through Qt signals, which
are safe to emit from any thread.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from fizzy import prompts
from fizzy.ai.base import Message, Provider, ProviderError, Request
from fizzy.runtime import AsyncRunner
from fizzy.settings import Settings

log = logging.getLogger(__name__)

HISTORY_TURNS = 8   # question/answer pairs remembered


class Session(QObject):
    state_changed = pyqtSignal(str)
    answer_started = pyqtSignal(str)        # the question
    answer_chunk = pyqtSignal(str)
    answer_done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, settings: Settings, runner: AsyncRunner, provider: Provider):
        super().__init__()
        self.settings = settings
        self.runner = runner
        self.provider = provider
        self.state = "idle"
        self._task: Optional[asyncio.Task] = None
        self._history: list[Message] = []
        self.last_answer = ""

    # ── called from the Qt thread ───────────────────────────────────────

    def ask_text(self, text: str) -> None:
        self.runner.submit(self._start(self._turn(text)), on_error=self._report)

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

    async def _turn(self, question: str) -> None:
        self._set_state("thinking")
        self.answer_started.emit(question)
        req = Request(
            system=prompts.system_prompt(self._context_lines()),
            text=question,
            history=list(self._history),
            model=self.settings.model_for(self.provider.id),
        )
        answer = await self._stream(req)
        self._remember(question, answer)
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

    def _context_lines(self) -> list[str]:
        return [f"Today is {datetime.now():%A, %d %B %Y}, local time {datetime.now():%H:%M}."]

    def _remember(self, question: str, answer: str) -> None:
        self.last_answer = answer
        self._history += [Message("user", question), Message("assistant", answer)]
        self._history = self._history[-HISTORY_TURNS * 2:]

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _report(self, exc: BaseException) -> None:
        self.error.emit(str(exc))
        self._set_state("idle")
