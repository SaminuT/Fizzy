"""Microphone input: 16 kHz mono, 16-bit, in 30 ms frames."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)

RATE = 16_000
FRAME = 480                     # 30 ms
BYTES_PER_SECOND = RATE * 2


def list_inputs() -> list[tuple[int, str]]:
    import sounddevice as sd
    out = []
    try:
        default_api = sd.default.hostapi if isinstance(sd.default.hostapi, int) else None
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] <= 0:
                continue
            # The same mic shows up once per Windows audio API; keep one copy.
            if default_api is not None and dev["hostapi"] != default_api:
                continue
            out.append((i, dev["name"]))
    except Exception:
        log.exception("couldn't list microphones")
    return out


class Microphone:
    """Always-open input stream. Frames are only kept while recording.

    on_level(rms) fires for every frame (0.0–1.0), recording or not, which
    drives the level meter and the wake-word listener. on_frame(bytes) is an
    optional tap for the wake-word listener.
    """

    def __init__(self, device: Optional[int] = None,
                 on_level: Optional[Callable[[float], None]] = None):
        self.device = device
        self.on_level = on_level
        self.on_frame: Optional[Callable[[bytes], None]] = None
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False
        self._chunks: list[bytes] = []

    def open(self) -> None:
        import sounddevice as sd
        if self._stream is not None:
            return
        self._stream = sd.RawInputStream(
            samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME,
            device=self.device, callback=self._callback,
        )
        self._stream.start()
        log.info("microphone open (device=%s)", self.device)

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def reopen(self, device: Optional[int]) -> None:
        self.close()
        self.device = device
        self.open()

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def start_recording(self) -> None:
        with self._lock:
            self._chunks = []
            self._recording = True

    def stop_recording(self) -> bytes:
        with self._lock:
            self._recording = False
            data = b"".join(self._chunks)
            self._chunks = []
        return data

    def _callback(self, indata, _frames, _time, status) -> None:
        if status:
            log.debug("mic status: %s", status)
        data = bytes(indata)
        with self._lock:
            if self._recording:
                self._chunks.append(data)
        try:
            if self.on_level is not None:
                self.on_level(rms(data))
            if self.on_frame is not None:
                self.on_frame(data)
        except Exception:
            # Never let an exception escape into PortAudio's thread.
            log.debug("mic listener failed", exc_info=True)


def rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(a * a)))


def pcm_to_wav(pcm: bytes, rate: int = RATE) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()
