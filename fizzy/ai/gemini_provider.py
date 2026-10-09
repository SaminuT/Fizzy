"""Gemini, through Google's GenAI SDK."""

from __future__ import annotations

import base64
from typing import AsyncIterator

from fizzy.ai.base import ModelInfo, Provider, ProviderError, Request
from fizzy.settings import get_secret

# Gemini variants that don't do text chat.
_SKIP = ("embedding", "imagen", "image", "tts", "live", "audio", "aqa", "veo", "learnlm")


class GeminiProvider(Provider):
    id = "gemini"
    label = "Gemini"
    default_model = "gemini-3.8-flash"

    def __init__(self):
        self._client = None

    def is_configured(self) -> bool:
        return bool(get_secret("gemini_api_key"))

    def _api(self):
        if self._client is None:
            from google import genai
            key = get_secret("gemini_api_key")
            if not key:
                raise ProviderError("Add your Gemini API key under Tray → Keys and sign-in.")
            self._client = genai.Client(api_key=key)
        return self._client

    def _contents(self, req: Request) -> list:
        from google.genai import types
        contents = [
            types.Content(role="model" if m.role == "assistant" else "user", parts=[types.Part.from_text(text=m.text)])
            for m in req.history
        ]
        parts = [types.Part.from_bytes(data=base64.b64decode(i.jpeg_b64), mime_type="image/jpeg") for i in req.images]
        parts.append(types.Part.from_text(text=req.text))
        contents.append(types.Content(role="user", parts=parts))
        return contents

    async def stream(self, req: Request) -> AsyncIterator[str]:
        from google.genai import errors, types
        model = self.model_or_default(req)
        config = types.GenerateContentConfig(system_instruction=req.system, max_output_tokens=req.max_tokens * 3)
        try:
            stream = await self._api().aio.models.generate_content_stream(
                model=model, contents=self._contents(req), config=config)
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except errors.ClientError as e:
            if e.code in (401, 403):
                raise ProviderError("Google didn't accept the Gemini API key.") from e
            if e.code == 404:
                raise ProviderError(f"Gemini model '{model}' isn't available. Pick another one.") from e
            if e.code == 429:
                raise ProviderError("Gemini says you're over your quota. Wait a bit or pick another model.") from e
            raise ProviderError(f"Gemini refused the request: {e.message}") from e

    async def list_models(self) -> list[ModelInfo]:
        out = []
        async for m in await self._api().aio.models.list():
            name = (m.name or "").removeprefix("models/")
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" not in actions or any(s in name for s in _SKIP):
                continue
            out.append(ModelInfo(name, m.display_name or ""))
        out.sort(key=lambda m: m.id, reverse=True)
        return out
