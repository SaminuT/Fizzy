"""Answers billed to the user's ChatGPT plan, through the Responses API.

The plan-usage route has its own rules: every request must stream and set
store=false, the system prompt goes in `instructions`, history is sent in
`input` each time, and several parameters (max_output_tokens, temperature…)
aren't accepted.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from fizzy.ai import chatgpt_auth
from fizzy.ai.base import ModelInfo, Provider, ProviderError, Request

log = logging.getLogger(__name__)

API_BASE = chatgpt_auth.RESOURCE

USAGE_PAGE = "ChatGPT → Settings → Usage"

_ERROR_TEXT = {
    "subscription_sharing_user_not_eligible": "Your ChatGPT plan can't be used from other apps. "
                                              "Use an OpenAI API key instead.",
    "subscription_sharing_usage_limit_exceeded": f"You've reached the usage limit for apps on your "
                                                 f"ChatGPT plan. See {USAGE_PAGE}.",
    "subscription_sharing_usage_unavailable": "ChatGPT plan usage is unavailable right now. Try again shortly.",
    "subscription_sharing_user_unavailable": "ChatGPT couldn't load your account just now. Try again shortly.",
    "subscription_sharing_invalid_user": "ChatGPT didn't accept the sign-in. If this keeps happening, "
                                         "sign out and back in from the tray.",
    "chatpass_v2_scope_not_authorized": "Fizzy isn't allowed to use your ChatGPT plan. Sign in again and approve it.",
}


class ChatGPTProvider(Provider):
    id = "chatgpt"
    label = "ChatGPT (sign-in)"
    default_model = "gpt-6.1-sol"

    def __init__(self):
        self._client = None

    def is_configured(self) -> bool:
        s = chatgpt_auth.load()
        return s.signed_in and s.plan_enabled

    async def _api(self):
        token = await chatgpt_auth.access_token()
        if self._client is None:
            from openai import AsyncOpenAI
            # Retrying is the app's decision on this route, not the SDK's.
            self._client = AsyncOpenAI(api_key=token, base_url=API_BASE, max_retries=0)
        self._client.api_key = token
        return self._client

    @staticmethod
    def _input(req: Request) -> list[dict]:
        items: list[dict] = []
        for m in req.history:
            kind = "output_text" if m.role == "assistant" else "input_text"
            items.append({"role": m.role, "content": [{"type": kind, "text": m.text}]})
        content: list[dict] = [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{i.jpeg_b64}"}
                               for i in req.images]
        content.append({"type": "input_text", "text": req.text})
        items.append({"role": "user", "content": content})
        return items

    async def stream(self, req: Request) -> AsyncIterator[str]:
        import openai
        try:
            client = await self._api()
        except chatgpt_auth.SignInError as e:
            raise ProviderError(str(e)) from e

        params = {
            "model": self.model_or_default(req),
            "instructions": req.system,
            "input": self._input(req),
            "store": False,
            "stream": True,
            "reasoning": {"effort": "low"},     # spoken answers should start quickly
        }
        for attempt in range(3):
            try:
                stream = await client.responses.create(**params)
                async for event in stream:
                    kind = getattr(event, "type", "")
                    if kind == "response.output_text.delta":
                        yield event.delta
                    elif kind == "response.failed":
                        err = getattr(event.response, "error", None)
                        raise ProviderError(_message(getattr(err, "code", ""), getattr(err, "message", "")))
                    elif kind == "error":
                        raise ProviderError(_message(getattr(event, "code", ""), getattr(event, "message", "")))
                    elif kind == "response.completed":
                        return
                return
            except openai.APIStatusError as e:
                code, param = _error_fields(e)
                if code == "subscription_sharing_unsupported_capability" and param and attempt < 2:
                    # Drop whatever the route doesn't support and ask again.
                    top = param.split(".")[0]
                    if top in params and top not in ("model", "input", "instructions", "store", "stream"):
                        log.info("ChatGPT route rejected %r; retrying without it", top)
                        params.pop(top)
                        continue
                if e.status_code == 401 and not code:
                    raise ProviderError("ChatGPT rejected the sign-in. Sign out and back in from the tray.") from e
                raise ProviderError(_message(code, getattr(e, "message", str(e)))) from e
            except openai.APIConnectionError as e:
                raise ProviderError("Couldn't reach OpenAI. Check your internet connection.") from e

    async def list_models(self) -> list[ModelInfo]:
        client = await self._api()
        page = await client.models.list()
        out = []
        for m in page.data:
            visibility = getattr(m, "visibility", None) or (m.model_extra or {}).get("visibility")
            if visibility in ("list", None):
                out.append(ModelInfo(m.id))
        return out

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


def _error_fields(e) -> tuple[str, str]:
    body = getattr(e, "body", None) or {}
    err = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(err, dict):
        return "", ""
    return err.get("code") or "", err.get("param") or ""


def _message(code: str, fallback: str) -> str:
    return _ERROR_TEXT.get(code) or f"ChatGPT request failed: {fallback or code or 'unknown error'}"
