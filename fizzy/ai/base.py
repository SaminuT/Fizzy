"""The interface every AI provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class Image:
    """A JPEG sent to the model, with the size it was encoded at."""
    jpeg_b64: str
    width: int
    height: int


@dataclass
class Message:
    role: str           # "user" | "assistant"
    text: str


@dataclass
class Request:
    system: str
    text: str
    history: list[Message] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    model: Optional[str] = None
    max_tokens: int = 1024


@dataclass
class ModelInfo:
    id: str
    label: str = ""

    @property
    def title(self) -> str:
        return self.label or self.id


class ProviderError(RuntimeError):
    """An error worth showing to the user as-is."""


class Provider(ABC):
    id: str = ""
    label: str = ""
    default_model: str = ""
    vision: bool = True     # can it read screenshots?

    def is_configured(self) -> bool:
        """True when the provider has what it needs (a key, a sign-in…)."""
        return True

    @abstractmethod
    def stream(self, req: Request) -> AsyncIterator[str]:
        """Yield the answer as it arrives."""

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(self.default_model)]

    async def complete(self, req: Request) -> str:
        parts = []
        async for chunk in self.stream(req):
            parts.append(chunk)
        return "".join(parts)

    async def aclose(self) -> None:
        """Release network clients."""

    def model_or_default(self, req: Request) -> str:
        return req.model or self.default_model
