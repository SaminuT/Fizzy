"""GitHub Copilot, signed in with GitHub's device-code flow.

GitHub has no public Copilot chat API. This uses the same OAuth app id and
endpoints the VS Code Copilot extension uses, as many community editors do;
it's unofficial and could change. Usage counts against the user's Copilot
seat as normal.
"""

from __future__ import annotations

import asyncio
import logging
import time
import webbrowser
from typing import Callable, Optional

import httpx

from fizzy.ai.base import ModelInfo, ProviderError, Request
from fizzy.ai.openai_provider import OpenAICompatible
from fizzy.settings import get_secret, set_secret

log = logging.getLogger(__name__)

CLIENT_ID = "Iv1.b507a08c87ecfe98"         # VS Code's public Copilot OAuth app
DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_API = "https://api.githubcopilot.com"
EDITOR_HEADERS = {
    "Editor-Version": "vscode/1.105.0",
    "Editor-Plugin-Version": "copilot-chat/0.32.0",
    "Copilot-Integration-Id": "vscode-chat",
    "User-Agent": "GitHubCopilotChat/0.32.0",
}
SECRET_NAME = "github_token"


async def device_sign_in(on_code: Callable[[str, str], None], open_browser=webbrowser.open) -> str:
    """Run the device flow; on_code(user_code, url) is called once the code is known."""
    async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/json"}) as c:
        r = await c.post(DEVICE_URL, data={"client_id": CLIENT_ID, "scope": "read:user"})
        r.raise_for_status()
        d = r.json()
        on_code(d["user_code"], d["verification_uri"])
        open_browser(d["verification_uri"])

        interval = int(d.get("interval", 5))
        deadline = time.monotonic() + int(d.get("expires_in", 900))
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            r = await c.post(TOKEN_URL, data={
                "client_id": CLIENT_ID,
                "device_code": d["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
            body = r.json() if r.status_code == 200 else {}
            if body.get("access_token"):
                set_secret(SECRET_NAME, body["access_token"])
                return body["access_token"]
            err = body.get("error")
            if err == "slow_down":
                interval += 5
            elif err in ("expired_token", "access_denied"):
                raise ProviderError("GitHub sign-in was cancelled or expired.")
    raise ProviderError("GitHub sign-in timed out.")


def sign_out() -> None:
    set_secret(SECRET_NAME, None)


class CopilotProvider(OpenAICompatible):
    id = "copilot"
    label = "GitHub Copilot"
    default_model = "gpt-4.1"

    def __init__(self):
        super().__init__(base_url=DEFAULT_API)
        self._copilot_token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def is_configured(self) -> bool:
        return bool(get_secret(SECRET_NAME))

    async def _refresh(self) -> None:
        """Swap the long-lived GitHub token for a short-lived Copilot one."""
        async with self._lock:
            if time.time() < self._expires_at - 60:
                return
            gh = get_secret(SECRET_NAME)
            if not gh:
                raise ProviderError("Sign in to GitHub Copilot first (Tray → Keys and sign-in).")
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(COPILOT_TOKEN_URL, headers={"Authorization": f"token {gh}", **EDITOR_HEADERS})
            if r.status_code == 401:
                sign_out()
                raise ProviderError("GitHub sign-in expired. Sign in to Copilot again from the tray.")
            if r.status_code == 403:
                raise ProviderError("This GitHub account doesn't have Copilot.")
            r.raise_for_status()
            data = r.json()
            self._copilot_token = data["token"]
            self._expires_at = float(data.get("expires_at", time.time() + 1500))
            api = (data.get("endpoints") or {}).get("api") or DEFAULT_API
            if self._client is not None and api != self.base_url:
                await self._client.close()
                self._client = None
            self.base_url = api

    def _key(self) -> Optional[str]:
        return self._copilot_token

    def _default_headers(self) -> dict:
        return dict(EDITOR_HEADERS)

    def _request_headers(self, req: Request) -> dict:
        # Copilot only accepts images on requests flagged as vision requests.
        return {"Copilot-Vision-Request": "true"} if req.images else {}

    def _api(self):
        client = super()._api()
        client.api_key = self._copilot_token      # rotates every ~25 minutes
        return client

    async def stream(self, req: Request):
        await self._refresh()
        async for piece in super().stream(req):
            yield piece

    async def list_models(self) -> list[ModelInfo]:
        await self._refresh()
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{self.base_url}/models",
                            headers={"Authorization": f"Bearer {self._copilot_token}", **EDITOR_HEADERS})
        r.raise_for_status()
        out = []
        for m in r.json().get("data", []):
            caps = m.get("capabilities") or {}
            if caps.get("type") != "chat" or m.get("model_picker_enabled") is False:
                continue
            out.append(ModelInfo(m["id"], m.get("name", "")))
        return out
