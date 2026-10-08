"""Play 16-bit mono audio, stoppable at any moment."""

from __future__ import annotations

import threading

import numpy as np


class Player:
    def __init__(self, device=None):
        self.device = device
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def stop(self) -> None:
        self._stop.set()

    def play(self, samples: np.ndarray, rate: int) -> bool:
        """Block until the clip finishes. False if it was stopped part-way."""
        import sounddevice as sd

        if samples.size == 0:
            return True
        with self._lock:            # one clip at a time
            self._stop.clear()
            pos = 0
            done = threading.Event()
            data = samples.astype(np.int16, copy=False)

            def callback(outdata, frames, _time, _status):
                nonlocal pos
                if self._stop.is_set():
                    outdata.fill(0)
                    raise sd.CallbackStop
                chunk = data[pos:pos + frames]
                outdata[:len(chunk), 0] = chunk
                if len(chunk) < frames:
                    outdata[len(chunk):, 0] = 0
                    raise sd.CallbackStop
                pos += frames

            with sd.OutputStream(samplerate=rate, channels=1, dtype="int16", device=self.device,
                                 callback=callback, finished_callback=done.set):
                while not done.wait(0.05):
                    pass
            return not self._stop.is_set()
