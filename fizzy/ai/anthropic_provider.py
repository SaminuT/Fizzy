"""Claude, through Anthropic's API."""

from __future__ import annotations

from typing import AsyncIterator

from fizzy.ai.base import ModelInfo, Provider, ProviderError, Request
from fizzy.settings import get_secret


class AnthropicProvider(Provider):
    id = "anthropic"
    label = "Claude"
    default_model = "claude-sonnet-5-5"

    def __init__(self):
        self._client = None

    def is_configured(self) -> bool:
        return bool(get_secret("anthropic_api_key"))

    def _api(self):
        if self._client is None:
            import anthropic
            key = get_secret("anthropic_api_key")
            if not key:
                raise ProviderError("Add your Anthropic API key under Tray → Keys and sign-in.")
            self._client = anthropic.AsyncAnthropic(api_key=key)
        return self._client

    @staticmethod
    def _messages(req: Request) -> list[dict]:
        msgs = [{"role": m.role, "content": m.text} for m in req.history]
        content: list[dict] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img.jpeg_b64}}
            for img in req.images
        ]
        content.append({"type": "text", "text": req.text})
        msgs.append({"role": "user", "content": content})
        return msgs

    async def stream(self, req: Request) -> AsyncIterator[str]:
        import anthropic
        client = self._api()
        model = self.model_or_default(req)
        try:
            async with client.messages.stream(
                model=model,
                max_tokens=req.max_tokens,
                system=req.system,
                messages=self._messages(req),
            ) as s:
                async for text in s.text_stream:
                    yield text
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic didn't accept the API key. Check it under Tray → Keys and sign-in.") from e
        except anthropic.NotFoundError as e:
            raise ProviderError(f"Claude model '{model}' isn't available. Pick another one in the panel.") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("Claude is rate-limiting this key. Wait a moment and try again.") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("Couldn't reach Anthropic. Check your internet connection.") from e

    async def list_models(self) -> list[ModelInfo]:
        client = self._api()
        page = await client.models.list(limit=100)
        items = sorted(page.data, key=lambda m: m.created_at, reverse=True)
        return [ModelInfo(m.id, getattr(m, "display_name", "") or "") for m in items]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
