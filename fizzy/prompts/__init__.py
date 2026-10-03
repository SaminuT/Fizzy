"""Prompt text shipped with Fizzy."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=None)
def load(name: str) -> str:
    return resources.files(__name__).joinpath(f"{name}.md").read_text(encoding="utf-8")


def system_prompt(context_lines: list[str], extra: str = "") -> str:
    context = "\n".join(f"- {line}" for line in context_lines) or "- Nothing extra."
    text = load("system").replace("{context}", context)
    return text + ("\n" + extra if extra else "")
