"""OpenAI, or any server that speaks the OpenAI chat API (DeepSeek, OpenRouter, LM Studio…)."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Optional

from fizzy.ai.base import ModelInfo, Provider, ProviderError, Request
from fizzy.settings import get_secret

log = logging.getLogger(__name__)

# Families that can't hold a chat or see images; hidden from the picker.
_NOT_CHAT = re.compile(r"(embedding|whisper|tts|transcribe|dall-e|image|moderation|realtime|audio|search|"
                       r"davinci|babbage|codex|computer-use|sora)", re.IGNORECASE)


def _thinks(model: str) -> bool:
    """Reasoning models: o-series and GPT-5 onwards."""
    m = re.match(r"gpt-(\d+)", model)
    if m:
        return int(m.group(1)) >= 5 and "chat" not in model
    return bool(re.match(r"o\d", model))


class OpenAICompatible(Provider):
    """Shared by OpenAI and local OpenAI-style servers."""

    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base_url = base_url
        self._api_key = api_key
        self._client = None

    def _key(self) -> Optional[str]:
        return self._api_key

    def _api(self):
        if self._client is None:
            from openai import AsyncOpenAI
            key = self._key()
            if not key:
                raise ProviderError(f"Add your {self.label} API key under Tray → Keys and sign-in.")
            kwargs = {"api_key": key, "max_retries": 1}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    @property
    def official(self) -> bool:
        return not self.base_url or "api.openai.com" in self.base_url

    def _messages(self, req: Request) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": req.system}]
        msgs += [{"role": m.role, "content": m.text} for m in req.history]
        if req.images:
            content: list[dict] = [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{i.jpeg_b64}", "detail": "high"}}
                for i in req.images
            ]
            content.append({"type": "text", "text": req.text})
            msgs.append({"role": "user", "content": content})
        else:
            msgs.append({"role": "user", "content": req.text})
        return msgs

    def _params(self, model: str, req: Request) -> dict:
        params: dict = {"model": model, "messages": self._messages(req), "stream": True}
        if self.official:
            thinks = _thinks(model)
            # Thinking tokens count against the same limit, so leave room.
            params["max_completion_tokens"] = req.max_tokens * (3 if thinks else 1)
            if thinks:
                params["reasoning_effort"] = "low"   # spoken answers should start quickly
        else:
            params["max_tokens"] = req.max_tokens
        return params

    @staticmethod
    def _relax(params: dict, error: str) -> bool:
        """Drop or rename the parameter a server complained about. True if changed."""
        e = error.lower()
        if "reasoning_effort" in e and "reasoning_effort" in params:
            params.pop("reasoning_effort")
            return True
        if "max_completion_tokens" in e and "max_completion_tokens" in params:
            params["max_tokens"] = params.pop("max_completion_tokens")
            return True
        if "max_tokens" in e and "max_tokens" in params:
            params["max_completion_tokens"] = params.pop("max_tokens")
            return True
        if ("image" in e or "vision" in e) and any(isinstance(m["content"], list) for m in params["messages"]):
            for m in params["messages"]:
                if isinstance(m["content"], list):
                    m["content"] = next(c["text"] for c in m["content"] if c["type"] == "text")
            log.warning("model rejected images; asking without the screenshot")
            return True
        return False

    async def stream(self, req: Request) -> AsyncIterator[str]:
        import openai
        client = self._api()
        model = self.model_or_default(req)
        params = self._params(model, req)
        for attempt in range(4):
            try:
                stream = await client.chat.completions.create(**params)
                break
            except openai.BadRequestError as e:
                if attempt < 3 and self._relax(params, str(e)):
                    continue
                raise ProviderError(f"{self.label} refused the request: {e.message}") from e
            except openai.AuthenticationError as e:
                raise ProviderError(f"{self.label} didn't accept the API key.") from e
            except openai.NotFoundError as e:
                raise ProviderError(f"{self.label} doesn't offer the model '{model}'. Pick another one.") from e
            except openai.PermissionDeniedError as e:
                raise ProviderError(f"Your {self.label} account can't use '{model}'. Pick another model.") from e
            except openai.RateLimitError as e:
                raise ProviderError(f"{self.label} says you're over your limit or out of credit.") from e
            except openai.APIConnectionError as e:
                raise ProviderError(f"Couldn't reach {self.label} at {self.base_url or 'api.openai.com'}.") from e

        finish = None
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta and choice.delta.content:
                yield choice.delta.content
            finish = choice.finish_reason or finish
        if finish == "length":
            log.info("%s stopped at the token limit", model)

    async def list_models(self) -> list[ModelInfo]:
        page = await self._api().models.list()
        items = [m for m in page.data if not _NOT_CHAT.search(m.id)]
        items.sort(key=lambda m: getattr(m, "created", 0) or 0, reverse=True)
        return [ModelInfo(m.id) for m in items]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


class OpenAIProvider(OpenAICompatible):
    id = "openai"
    label = "OpenAI"
    default_model = "gpt-6-sol"

    def __init__(self, base_url: str = ""):
        super().__init__(base_url=base_url)

    def _key(self) -> Optional[str]:
        return get_secret("openai_api_key")

    def is_configured(self) -> bool:
        return bool(self._key())
