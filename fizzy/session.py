"""One conversation turn at a time: question in, answer out.

The Qt side calls ask_text(), start_listening() / stop_listening() and
cancel(). Everything slow runs on the background asyncio loop, and results
come back through Qt signals, which are safe to emit from any thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from fizzy import intent, prompts
from fizzy.ai.base import Message, Provider, ProviderError, Request
from fizzy.context import privacy, selection
from fizzy.context.gather import Context, compose_question, gather
from fizzy.context.tracker import ForegroundTracker
from fizzy.context.window import WindowInfo
from fizzy.runtime import AsyncRunner
from fizzy.settings import CONTEXT_SCREEN, Settings
from fizzy.speech import stt, tts
from fizzy.speech.endpoint import Endpointer
from fizzy.speech.mic import BYTES_PER_SECOND, FRAME, RATE, Microphone
from fizzy.speech.text import split_steps

log = logging.getLogger(__name__)

HISTORY_TURNS = 8   # question/answer pairs remembered per app
STEP_BY_STEP_MIN = 3    # answers with this many numbered steps are spoken one step at a time
MIN_AUDIO_S = 0.3
STT_TIMEOUT_S = 120


class Session(QObject):
    state_changed = pyqtSignal(str)
    answer_started = pyqtSignal(str)        # the question
    answer_chunk = pyqtSignal(str)
    answer_done = pyqtSignal(str)
    error = pyqtSignal(str)
    notice = pyqtSignal(str)                # short status note, e.g. "Didn't catch that"
    level = pyqtSignal(float)               # mic level while listening
    heard = pyqtSignal(str)                 # what speech-to-text made of it

    def __init__(self, settings: Settings, runner: AsyncRunner, provider: Provider,
                 tracker: ForegroundTracker, mic: Microphone):
        super().__init__()
        self.settings = settings
        self.runner = runner
        self.provider = provider
        self.tracker = tracker
        self.mic = mic
        self.mic.on_level = self._on_mic_level
        self._transcriber: Optional[stt.Transcriber] = None
        self._speaker: Optional[tts.Speaker] = None
        self._steps: list[str] = []
        self._step = 0
        self._last_spoken = ""
        self._endpointer: Optional[Endpointer] = None
        self._ep_lock = threading.Lock()
        self._utterance_over = threading.Event()
        self._pressed_at = 0.0
        self.state = "idle"
        self._task: Optional[asyncio.Task] = None
        # Separate history per app, so a chat about Excel doesn't leak into VS Code.
        self._history: dict[str, list[Message]] = {}
        self.last_answer = ""
        self.last_context: Optional[Context] = None

    # ── called from the Qt thread ───────────────────────────────────────

    def ask_text(self, text: str, highlighted: Optional[str] = None) -> None:
        """A typed question, with the highlighted text to include, if any."""
        win = self.tracker.current()
        self.runner.submit(self._start(self._handle(text, win, highlighted, spoken=self.settings.speak_typed)),
                           on_error=self._report)

    def start_listening(self) -> None:
        """Hotkey down (or wake word): start recording a spoken question."""
        if self.state == "listening":
            return
        self.stop_speaking()            # talking over Fizzy interrupts it
        self._pressed_at = time.monotonic()
        win = self.tracker.current()
        self.runner.submit(self._start(self._voice_turn(win)), on_error=self._report)

    def stop_listening(self) -> None:
        """Hotkey up. A quick tap keeps listening until the user goes quiet;
        a hold ends the recording on release."""
        if time.monotonic() - self._pressed_at >= self.settings.hold_threshold_s:
            self._utterance_over.set()

    def cancel(self) -> None:
        self._utterance_over.set()
        self.stop_speaking()
        self.runner.loop.call_soon_threadsafe(self._cancel_now)

    def stop_speaking(self) -> None:
        if self._speaker is not None:
            self._speaker.stop()

    def reset_voice(self) -> None:
        """Pick the text-to-speech service again (keys or settings changed)."""
        old, self._speaker = self._speaker, None
        if old is not None:
            old.stop()
            self.runner.submit(old.voice.aclose())

    def reset_transcriber(self) -> None:
        """Pick the speech-to-text service again (keys or settings changed)."""
        old, self._transcriber = self._transcriber, None
        if old is not None:
            self.runner.submit(old.aclose())

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

    async def _voice_turn(self, win: WindowInfo) -> None:
        sel_mode = self.settings.screen_context != CONTEXT_SCREEN
        sensitive = self.settings.privacy_guard and privacy.is_sensitive(win)
        # Read the selection now, while the user's app still has focus.
        uia = asyncio.create_task(asyncio.to_thread(selection.read_uia)) if sel_mode and not sensitive else None

        pcm = await self._record()
        if len(pcm) < MIN_AUDIO_S * BYTES_PER_SECOND:
            if uia:
                uia.cancel()
            return

        self._set_state("thinking")
        if self._transcriber is None:
            self._transcriber = stt.choose(self.settings)
        try:
            text = await asyncio.wait_for(self._transcriber.transcribe(pcm), STT_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise ProviderError("Speech-to-text took too long. Try again, or pick a smaller Whisper model.")
        log.info("heard: %r (%.1fs of audio)", text[:120], len(pcm) / BYTES_PER_SECOND)
        if not text:
            self.notice.emit("Didn't catch that. Try again?")
            return
        self.heard.emit(text)
        if await self._command(text):
            return

        picked = selection.clean(await uia) if uia else None
        if picked is None and sel_mode and not sensitive and self.settings.clipboard_fallback                 and selection.clipboard_allowed(win):
            # The hotkey is released by now, so Ctrl+C reaches the app intact.
            picked = selection.clean(await asyncio.to_thread(selection.read_via_clipboard))
        await self._turn(text, win, picked, spoken=True)

    async def _record(self) -> bytes:
        if not self.mic.is_open:
            try:
                self.mic.open()
            except Exception as e:
                raise ProviderError(f"Couldn't open the microphone: {e}") from e
        self._utterance_over.clear()
        with self._ep_lock:
            self._endpointer = Endpointer()
        self.mic.start_recording()
        self._set_state("listening")
        try:
            while not self._utterance_over.is_set():
                await asyncio.sleep(0.03)
        finally:
            with self._ep_lock:
                self._endpointer = None
            pcm = self.mic.stop_recording()
            if not self.settings.wake_word:
                # Don't keep the mic (and Windows' mic-in-use light) on between questions.
                self.mic.close()
        return pcm

    def _on_mic_level(self, rms: float) -> None:
        # Runs on the audio thread for every 30 ms frame.
        with self._ep_lock:
            ep = self._endpointer
            if ep is not None and ep.feed(rms, FRAME / RATE):
                log.info("end of speech (%s)", ep.reason)
                self._utterance_over.set()
        if ep is not None:
            self.level.emit(rms)

    async def _handle(self, text: str, win: WindowInfo, highlighted: Optional[str], spoken: bool) -> None:
        if not await self._command(text):
            await self._turn(text, win, highlighted, spoken)

    async def _command(self, text: str) -> bool:
        """Quick commands that need no AI call. True if text was one."""
        if intent.is_stop(text):
            return True
        if intent.is_repeat(text) and self._last_spoken:
            await self._say(self._last_spoken)
            return True
        if intent.is_next(text) and self._steps:
            await self._next_step()
            return True
        return False

    async def _turn(self, question: str, win: WindowInfo, highlighted: Optional[str],
                    spoken: bool = False) -> None:
        self._set_state("thinking")
        self.answer_started.emit(question)
        ctx = await gather(self.settings, win, vision=self.provider.vision, selection=highlighted,
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
        if spoken:
            await self._speak_answer(answer)

    # ── speaking ────────────────────────────────────────────────────────

    async def _speak_answer(self, answer: str) -> None:
        intro, steps = split_steps(answer)
        if len(steps) >= STEP_BY_STEP_MIN:
            # Long walkthroughs are easier to follow one step at a time.
            self._steps, self._step = steps, 0
            text = f"{intro}\nStep 1. {steps[0]}\nSay next when you're ready."
        else:
            self._steps = []
            text = answer
        await self._say(text)

    async def _next_step(self) -> None:
        self._step += 1
        if self._step >= len(self._steps):
            self._steps = []
            await self._say("That was the last step.")
            return
        n, total = self._step + 1, len(self._steps)
        tail = "That's the last step." if n == total else "Say next for the following step."
        await self._say(f"Step {n}. {self._steps[self._step]}\n{tail}")

    async def _say(self, text: str) -> None:
        if self._speaker is None:
            self._speaker = tts.Speaker(tts.choose(self.settings))
        self._last_spoken = text
        self._set_state("speaking")
        try:
            await self._speaker.say(text)
        except ProviderError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("speech failed")
            self.notice.emit(f"Couldn't speak the answer ({self._speaker.voice.label}): {e}")

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
