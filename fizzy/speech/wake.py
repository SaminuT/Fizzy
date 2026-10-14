"""Hands-free start: say "Fizzy" (optionally followed by the question).

Off by default, because it keeps the microphone open. Audio never leaves
the PC: short bursts of speech are cut out by level, and only those are run
through a tiny local Whisper model to check for the name.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from fizzy.speech.mic import BYTES_PER_SECOND, FRAME, RATE, rms
from fizzy.speech.stt import LocalWhisper

log = logging.getLogger(__name__)

WAKE = re.compile(r"\b(?:hey|hi|okay|ok)?[\s,]*(fizzy|fizzie|fizzi|phizzy|fizz)\b[\s,.!?]*", re.IGNORECASE)
MIN_BURST_S = 0.3
MAX_BURST_S = 6.0
TAIL_SILENCE_S = 0.5
THRESHOLD = 0.012
FRAME_S = FRAME / RATE


def split_wake(text: str) -> Optional[str]:
    """None if the name wasn't said; otherwise whatever came after it ("" if nothing)."""
    m = WAKE.search(text)
    if not m:
        return None
    return text[m.end():].strip()


class WakeListener(QObject):
    woke = pyqtSignal(str)          # the rest of the sentence, "" if just the name

    def __init__(self, model_size: str = "tiny", parent=None):
        super().__init__(parent)
        self.whisper = LocalWhisper(model_size)
        self.paused = False
        self._bursts: "queue.Queue[bytes]" = queue.Queue(maxsize=4)
        self._buf = bytearray()
        self._in_speech = False
        self._quiet_s = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="fizzy-wake", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._bursts.put_nowait(b"")
        except queue.Full:
            pass

    def on_frame(self, pcm: bytes) -> None:
        """Called from the audio thread for every 30 ms frame."""
        if self.paused or self._stop.is_set():
            self._reset()
            return
        loud = rms(pcm) > THRESHOLD
        if loud:
            self._in_speech = True
            self._quiet_s = 0.0
        if self._in_speech:
            self._buf += pcm
            if not loud:
                self._quiet_s += FRAME_S
            length = len(self._buf) / BYTES_PER_SECOND
            if self._quiet_s >= TAIL_SILENCE_S or length >= MAX_BURST_S:
                if length >= MIN_BURST_S:
                    try:
                        self._bursts.put_nowait(bytes(self._buf))
                    except queue.Full:
                        pass        # still busy with earlier speech; drop this one
                self._reset()

    def _reset(self) -> None:
        self._buf = bytearray()
        self._in_speech = False
        self._quiet_s = 0.0

    def _worker(self) -> None:
        while not self._stop.is_set():
            burst = self._bursts.get()
            if not burst or self._stop.is_set():
                continue
            try:
                text = self.whisper._run(burst, prompt="Fizzy")
            except Exception:
                log.exception("wake-word check failed")
                continue
            rest = split_wake(text)
            if rest is not None and not self.paused:
                log.info("wake word heard: %r", text)
                self.woke.emit(rest)
