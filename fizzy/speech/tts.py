"""Text to speech: free Microsoft Edge voices by default, OpenAI or ElevenLabs with a key."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from fizzy.ai.base import ProviderError
from fizzy.settings import Settings, get_secret
from fizzy.speech.player import Player
from fizzy.speech.text import sentences

log = logging.getLogger(__name__)

Clip = tuple[np.ndarray, int]   # int16 samples, sample rate


class Voice(ABC):
    label = ""

    @abstractmethod
    async def synth(self, text: str) -> Clip: ...

    async def aclose(self) -> None:
        pass


class EdgeVoice(Voice):
    label = "Microsoft Edge voices"
    DEFAULT = "en-US-AvaMultilingualNeural"

    def __init__(self, voice: str = ""):
        self.voice = voice or self.DEFAULT

    async def synth(self, text: str) -> Clip:
        import edge_tts
        import miniaudio

        mp3 = bytearray()
        async for chunk in edge_tts.Communicate(text, self.voice).stream():
            if chunk["type"] == "audio":
                mp3 += chunk["data"]
        if not mp3:
            return np.zeros(0, dtype=np.int16), 24_000
        decoded = await asyncio.to_thread(
            miniaudio.decode, bytes(mp3), miniaudio.SampleFormat.SIGNED16, 1, 24_000)
        return np.frombuffer(decoded.samples, dtype=np.int16), decoded.sample_rate

    @staticmethod
    async def list_voices() -> list[tuple[str, str]]:
        import edge_tts
        voices = await edge_tts.list_voices()
        return sorted((v["ShortName"], f'{v["FriendlyName"]}') for v in voices)


class OpenAIVoice(Voice):
    label = "OpenAI"
    MODELS = ("gpt-4o-mini-tts", "tts-1")
    RATE = 24_000

    def __init__(self, key: str, voice: str = ""):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=key)
        self.voice = voice or "alloy"

    async def synth(self, text: str) -> Clip:
        import openai
        last: Exception | None = None
        for model in self.MODELS:
            try:
                r = await self._client.audio.speech.create(
                    model=model, voice=self.voice, input=text, response_format="pcm")
                return np.frombuffer(r.content, dtype=np.int16), self.RATE
            except (openai.NotFoundError, openai.BadRequestError) as e:
                last = e
        raise ProviderError(f"OpenAI speech failed: {last}")

    async def aclose(self) -> None:
        await self._client.close()


class ElevenLabsVoice(Voice):
    label = "ElevenLabs"
    RATE = 24_000
    DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"      # "Rachel", a stock voice

    def __init__(self, key: str, voice_id: str = ""):
        import httpx
        self._client = httpx.AsyncClient(timeout=30, headers={"xi-api-key": key})
        self.voice_id = voice_id or self.DEFAULT_VOICE

    async def synth(self, text: str) -> Clip:
        r = await self._client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            params={"output_format": f"pcm_{self.RATE}"},
            json={"text": text, "model_id": "eleven_flash_v2_5"},
        )
        if r.status_code == 401:
            raise ProviderError("ElevenLabs didn't accept the API key.")
        r.raise_for_status()
        return np.frombuffer(r.content, dtype=np.int16), self.RATE

    async def aclose(self) -> None:
        await self._client.aclose()


def choose(settings: Settings) -> Voice:
    want = settings.tts
    if want in ("auto", "elevenlabs"):
        key = get_secret("elevenlabs_api_key")
        if key:
            return ElevenLabsVoice(key, get_secret("elevenlabs_voice_id") or "")
    if want in ("auto", "openai"):
        key = get_secret("openai_api_key")
        if key and (want == "openai" or not settings.openai_base_url):
            return OpenAIVoice(key, settings.voice if want == "openai" else "")
    return EdgeVoice(settings.voice if want in ("auto", "edge") else "")


class Speaker:
    """Speaks text sentence by sentence, preparing the next while one plays."""

    def __init__(self, voice: Voice, player: Optional[Player] = None):
        self.voice = voice
        self.player = player or Player()

    def stop(self) -> None:
        self.player.stop()

    async def say(self, text: str) -> None:
        parts = sentences(text)
        if not parts:
            return
        pending = asyncio.create_task(self.voice.synth(parts[0]))
        try:
            for i in range(len(parts)):
                clip = await pending
                if i + 1 < len(parts):
                    pending = asyncio.create_task(self.voice.synth(parts[i + 1]))
                finished = await asyncio.to_thread(self.player.play, *clip)
                if not finished:
                    break
        except asyncio.CancelledError:
            self.player.stop()
            raise
        finally:
            if not pending.done():
                pending.cancel()
