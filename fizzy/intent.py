"""Cheap, local reading of what a question is asking for."""

from __future__ import annotations

import re

_POINTING = re.compile(
    r"\b(where(?:'s| is| are| do i| can i| would i| should i)?|point(?:ing)? (?:at|to|out)|show me|"
    r"which (?:button|icon|menu|tab|option|setting|link)|find (?:the|a|my)|locate|"
    r"how do i (?:open|find|get to|reach)|what do i (?:click|press|tap)|click (?:on )?the)\b",
    re.IGNORECASE,
)

_LEADING = re.compile(
    r"^(?:hey fizzy[,!.]?\s*|fizzy[,!.]?\s*|please\s+|can you\s+|could you\s+)*"
    r"(?:where(?:'s| is| are| do i find| can i find| would i find| should i click)?|point (?:at|to|out)|show me(?: where)?|"
    r"find|locate|which (?:button|icon|menu|tab|option|setting|link)(?: is)?|"
    r"how do i (?:open|find|get to|reach)|what do i (?:click|press|tap)(?: to)?|click(?: on)?)\s+",
    re.IGNORECASE,
)
_TRAILING = re.compile(
    r"\s*(?:button|icon|menu|tab|option|setting|link|on (?:the|my) screen|here|in this (?:window|app|page))?"
    r"\s*(?:located|at|is)?\s*[?.!]*$",
    re.IGNORECASE,
)
_ARTICLE = re.compile(r"^(?:the|a|an|my|this|that)\s+", re.IGNORECASE)

_STOP = re.compile(r"^\s*(stop|cancel|never ?mind|be quiet|shut up|quiet)[.!]?\s*$", re.IGNORECASE)
_REPEAT = re.compile(r"^\s*(repeat( that)?|say (that|it) again|again|what did you say)[.!?]?\s*$", re.IGNORECASE)
_NEXT = re.compile(r"^\s*(next( step)?|continue|go on|ok(ay)?,? next|done,? next|what'?s next)[.!?]?\s*$",
                   re.IGNORECASE)


def wants_pointing(question: str) -> bool:
    return bool(_POINTING.search(question))


def target_phrase(question: str) -> str:
    """'Where is the Save button?' → 'Save'."""
    q = question.strip()
    q = _LEADING.sub("", q, count=1)
    q = _ARTICLE.sub("", q)
    q = _TRAILING.sub("", q)
    return q.strip(" \"'“”") or question.strip()


def is_stop(text: str) -> bool:
    return bool(_STOP.match(text))


def is_repeat(text: str) -> bool:
    return bool(_REPEAT.match(text))


def is_next(text: str) -> bool:
    return bool(_NEXT.match(text))
