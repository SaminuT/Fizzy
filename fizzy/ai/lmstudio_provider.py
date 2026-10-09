"""LM Studio's local server (OpenAI-compatible)."""

from __future__ import annotations

from typing import AsyncIterator

from fizzy.ai.base import ModelInfo, ProviderError, Request
from fizzy.ai.openai_provider import OpenAICompatible


class LMStudioProvider(OpenAICompatible):
    id = "lmstudio"
    label = "LM Studio"
    default_model = ""      # whatever model is loaded

    def __init__(self, host: str):
        # LM Studio ignores the key, but the client insists on one.
        super().__init__(base_url=host, api_key="lm-studio")

    async def stream(self, req: Request) -> AsyncIterator[str]:
        if not req.model:
            models = await self.list_models()
            if not models:
                raise ProviderError("LM Studio has no model loaded. Load one in LM Studio, then try again.")
            req.model = models[0].id
        try:
            async for piece in super().stream(req):
                yield piece
        except ProviderError as e:
            if "Couldn't reach" in str(e):
                raise ProviderError(
                    f"LM Studio's server isn't running at {self.base_url}. "
                    "In LM Studio open Developer → Start Server.") from e
            raise

    async def list_models(self) -> list[ModelInfo]:
        page = await self._api().models.list()
        return [ModelInfo(m.id) for m in page.data if "embed" not in m.id]
