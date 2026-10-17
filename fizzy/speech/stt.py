"""Speech to text: local Whisper by default, cloud services when configured."""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod

import numpy as np

from fizzy.ai.base import ProviderError
from fizzy.settings import Settings, get_secret
from fizzy.speech.mic import RATE, pcm_to_wav

log = logging.getLogger(__name__)

# Nudges Whisper towards spelling the name right.
NAME_HINT = "Fizzy"


class Transcriber(ABC):
    label = ""

    @abstractmethod
    async def transcribe(self, pcm: bytes) -> str: ...

    async def aclose(self) -> None:
        pass


class LocalWhisper(Transcriber):
    """faster-whisper on the CPU (or GPU when CUDA is available). Free, offline."""

    label = "Whisper (on this PC)"
    _models: dict = {}
    _load_lock = threading.Lock()
    cpu_only = False        # set once the GPU has failed, for every instance

    def __init__(self, size: str = "base"):
        self.size = size

    @classmethod
    def model(cls, size: str, cpu: bool = False):
        key = (size, cpu)
        with cls._load_lock:
            if key not in cls._models:
                from faster_whisper import WhisperModel
                log.info("loading Whisper '%s' on %s (first use downloads it)", size, "CPU" if cpu else "best device")
                try:
                    cls._models[key] = WhisperModel(size, device="cpu" if cpu else "auto", compute_type="int8")
                except Exception:
                    if cpu:
                        raise
                    log.info("GPU Whisper unavailable; using the CPU")
                    cls._models[key] = WhisperModel(size, device="cpu", compute_type="int8")
            return cls._models[key]

    def _run(self, pcm: bytes, prompt: str = NAME_HINT) -> str:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            return self._transcribe(self.model(self.size, cpu=self.cpu_only), audio, prompt)
        except RuntimeError as e:
            # A GPU can be detected while NVIDIA's CUDA libraries (cuBLAS, cuDNN)
            # aren't installed; that only fails here, on first use.
            if self.cpu_only or not any(k in str(e).lower() for k in ("cuda", "cublas", "cudnn")):
                raise
            log.warning("GPU Whisper failed (%s); switching to the CPU", e)
            LocalWhisper.cpu_only = True
            return self._transcribe(self.model(self.size, cpu=True), audio, prompt)

    @staticmethod
    def _transcribe(model, audio, prompt: str) -> str:
        segments, _info = model.transcribe(
            audio, beam_size=1, vad_filter=True, initial_prompt=prompt, condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    async def transcribe(self, pcm: bytes) -> str:
        return await asyncio.to_thread(self._run, pcm)


class OpenAITranscriber(Transcriber):
    label = "OpenAI"
    MODELS = ("gpt-4o-mini-transcribe", "whisper-1")

    def __init__(self, key: str, base_url: str = ""):
        from openai import AsyncOpenAI
        kwargs = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def transcribe(self, pcm: bytes) -> str:
        import openai
        wav = pcm_to_wav(pcm)
        last: Exception | None = None
        for model in self.MODELS:
            try:
                r = await self._client.audio.transcriptions.create(
                    model=model, file=("speech.wav", wav, "audio/wav"), prompt=NAME_HINT)
                return (r.text or "").strip()
            except (openai.NotFoundError, openai.BadRequestError) as e:
                last = e        # model not offered here; try the next one
        raise ProviderError(f"OpenAI transcription failed: {last}")

    async def aclose(self) -> None:
        await self._client.close()


class DeepgramTranscriber(Transcriber):
    label = "Deepgram"
    URL = "https://api.deepgram.com/v1/listen"

    def __init__(self, key: str):
        import httpx
        self._client = httpx.AsyncClient(timeout=30, headers={"Authorization": f"Token {key}"})

    async def transcribe(self, pcm: bytes) -> str:
        r = await self._client.post(
            self.URL,
            params={"model": "nova-3", "smart_format": "true", "detect_language": "true"},
            content=pcm,
            headers={"Content-Type": f"audio/l16;rate={RATE};channels=1"},
        )
        if r.status_code == 401:
            raise ProviderError("Deepgram didn't accept the API key.")
        r.raise_for_status()
        alts = r.json()["results"]["channels"][0]["alternatives"]
        return (alts[0]["transcript"] if alts else "").strip()

    async def aclose(self) -> None:
        await self._client.aclose()


def choose(settings: Settings) -> Transcriber:
    want = settings.stt
    if want in ("auto", "deepgram"):
        key = get_secret("deepgram_api_key")
        if key:
            return DeepgramTranscriber(key)
    if want in ("auto", "openai"):
        key = get_secret("openai_api_key")
        # A custom base URL points at someone else's server, which may not
        # do transcription, so only use OpenAI's own endpoint automatically.
        if key and (want == "openai" or not settings.openai_base_url):
            return OpenAITranscriber(key, settings.openai_base_url if want == "openai" else "")
    return LocalWhisper(settings.whisper_model)
