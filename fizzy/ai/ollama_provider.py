"""Ollama: models running on this PC."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from fizzy.ai.base import ModelInfo, Provider, ProviderError, Request


class OllamaProvider(Provider):
    id = "ollama"
    label = "Ollama"
    # Small, reads screenshots, and fast enough without a GPU.
    default_model = "qwen2.5vl:3b"

    def __init__(self, host: str):
        self.host = host.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.host, timeout=httpx.Timeout(300, connect=5))

    def _messages(self, req: Request) -> list[dict]:
        msgs = [{"role": "system", "content": req.system}]
        msgs += [{"role": m.role, "content": m.text} for m in req.history]
        user: dict = {"role": "user", "content": req.text}
        if req.images:
            user["images"] = [i.jpeg_b64 for i in req.images]
        msgs.append(user)
        return msgs

    async def stream(self, req: Request) -> AsyncIterator[str]:
        model = self.model_or_default(req)
        body = {
            "model": model,
            "messages": self._messages(req),
            "stream": True,
            "keep_alive": "15m",        # stay loaded between questions
            "options": {"num_predict": req.max_tokens},
        }
        try:
            async with self._client.stream("POST", "/api/chat", json=body) as r:
                if r.status_code == 404:
                    raise ProviderError(f"Ollama doesn't have '{model}'. Run: ollama pull {model}")
                if r.status_code >= 400:
                    detail = (await r.aread()).decode(errors="replace")[:300]
                    raise ProviderError(f"Ollama couldn't run '{model}': {detail}")
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise ProviderError(f"Ollama: {data['error']}")
                    piece = (data.get("message") or {}).get("content")
                    if piece:
                        yield piece
                    if data.get("done"):
                        break
        except httpx.ConnectError as e:
            raise ProviderError(f"Ollama isn't running at {self.host}. Start the Ollama app and try again.") from e

    async def list_models(self) -> list[ModelInfo]:
        r = await self._client.get("/api/tags")
        r.raise_for_status()
        models = r.json().get("models", [])
        models.sort(key=lambda m: m.get("modified_at", ""), reverse=True)
        return [ModelInfo(m["name"]) for m in models]

    async def is_running(self) -> bool:
        try:
            return (await self._client.get("/api/version", timeout=2)).status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
