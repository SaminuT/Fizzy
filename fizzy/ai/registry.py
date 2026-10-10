"""The list of providers, how to build each one, and a cache of their model lists."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable

from fizzy.ai.base import ModelInfo, Provider
from fizzy.paths import cache_dir
from fizzy.settings import Settings

log = logging.getLogger(__name__)

MODEL_CACHE_TTL_S = 24 * 3600


@dataclass(frozen=True)
class Entry:
    id: str
    label: str
    build: Callable[[Settings], Provider]
    local: bool = False         # runs on this PC, no account needed


def _anthropic(_s: Settings) -> Provider:
    from fizzy.ai.anthropic_provider import AnthropicProvider
    return AnthropicProvider()


def _openai(s: Settings) -> Provider:
    from fizzy.ai.openai_provider import OpenAIProvider
    return OpenAIProvider(s.openai_base_url)


def _gemini(_s: Settings) -> Provider:
    from fizzy.ai.gemini_provider import GeminiProvider
    return GeminiProvider()


def _ollama(s: Settings) -> Provider:
    from fizzy.ai.ollama_provider import OllamaProvider
    return OllamaProvider(s.ollama_host)


def _lmstudio(s: Settings) -> Provider:
    from fizzy.ai.lmstudio_provider import LMStudioProvider
    return LMStudioProvider(s.lmstudio_host)


ENTRIES: list[Entry] = [
    Entry("anthropic", "Claude", _anthropic),
    Entry("openai", "OpenAI", _openai),
    Entry("gemini", "Gemini", _gemini),
    Entry("ollama", "Ollama", _ollama, local=True),
    Entry("lmstudio", "LM Studio", _lmstudio, local=True),
]


def entry(pid: str) -> Entry:
    for e in ENTRIES:
        if e.id == pid:
            return e
    raise KeyError(pid)


def build(pid: str, settings: Settings) -> Provider:
    return entry(pid).build(settings)


def startup_provider(settings: Settings) -> Provider:
    """The saved choice if it's usable, else the first account that is, else Ollama."""
    try:
        p = build(settings.provider, settings)
        if p.is_configured():
            return p
    except KeyError:
        pass
    for e in ENTRIES:
        if e.local:
            continue
        p = e.build(settings)
        if p.is_configured():
            return p
    return build("ollama", settings)


# ── model list cache ────────────────────────────────────────────────────

def _cache_file():
    return cache_dir() / "models.json"


def _read_cache() -> dict:
    try:
        return json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cached_models(pid: str) -> tuple[list[ModelInfo], bool]:
    """(models, fresh). Empty list if never fetched."""
    item = _read_cache().get(pid)
    if not item:
        return [], False
    models = [ModelInfo(m[0], m[1]) for m in item.get("models", [])]
    return models, time.time() - item.get("at", 0) < MODEL_CACHE_TTL_S


def store_models(pid: str, models: list[ModelInfo]) -> None:
    data = _read_cache()
    data[pid] = {"at": time.time(), "models": [[m.id, m.label] for m in models]}
    try:
        _cache_file().write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        log.warning("couldn't write the model cache")


async def refresh_models(provider: Provider) -> list[ModelInfo]:
    models = await provider.list_models()
    if models:
        store_models(provider.id, models)
    return models
