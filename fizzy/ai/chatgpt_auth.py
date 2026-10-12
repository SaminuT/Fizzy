"""Sign in with ChatGPT (OpenAI's open-source plan-usage flow).

Fizzy registers itself the first time a user signs in (dynamic
registration, so no client secret ships with the app), gets an OAuth token
authorised for the user's ChatGPT plan, and refreshes it as it nears
expiry. The whole flow runs in the user's browser through a one-off
loopback listener on 127.0.0.1.

Tokens live in Windows Credential Manager under "chatgpt_session". The
issued client id and this PC's host id are kept across sign-outs, so
signing in again reuses the same registration.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from fizzy import APP_NAME
from fizzy.settings import get_json_secret, set_json_secret

log = logging.getLogger(__name__)

ISSUER = "https://auth.openai.com"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
REGISTRATION_CLIENT = "dynamic_agent_client"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"
PREFERRED_PORT = 1455
CALLBACK_PATH = "/auth/callback"
SIGN_IN_TIMEOUT_S = 300
REFRESH_MARGIN_S = 120

SECRET_NAME = "chatgpt_session"
TERMINAL_REFRESH_ERRORS = {
    "invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
    "refresh_token_invalidated", "refresh_token_reused",
}


class SignInError(RuntimeError):
    pass


class SignInNeeded(SignInError):
    """The saved sign-in can't be used any more; the user has to sign in again."""


@dataclass
class ChatGPTSession:
    ext_agent_host_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str = ""             # issued at first registration, kept for reauthorisation
    email: str = ""
    subject: str = ""
    id_token: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    scopes: str = ""

    @property
    def signed_in(self) -> bool:
        return bool(self.access_token and self.refresh_token)

    @property
    def plan_enabled(self) -> bool:
        return PLAN_SCOPE in self.scopes.split()

    def clear_tokens(self) -> None:
        self.access_token = self.refresh_token = ""
        self.expires_at = 0.0
        self.scopes = ""


def load() -> ChatGPTSession:
    raw = get_json_secret(SECRET_NAME) or {}
    known = ChatGPTSession.__dataclass_fields__
    return ChatGPTSession(**{k: v for k, v in raw.items() if k in known})


def save(s: ChatGPTSession) -> None:
    set_json_secret(SECRET_NAME, asdict(s))


# ── PKCE ────────────────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorize_url(sess: ChatGPTSession, redirect_uri: str, state: str, nonce: str, challenge: str) -> str:
    params = {
        "client_id": sess.client_id or REGISTRATION_CLIENT,
        "ext_agent_host_id": sess.ext_agent_host_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if sess.client_id:
        if sess.id_token:
            params["id_token_hint"] = sess.id_token     # skips the account picker
        if sess.email:
            params["login_hint"] = sess.email
    else:
        params["agent_name_hint"] = APP_NAME              # shown on the consent screen
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# ── loopback listener ───────────────────────────────────────────────────

_DONE_PAGE = (
    "<!doctype html><meta charset=utf-8><title>Fizzy</title>"
    "<body style='font-family:Segoe UI,sans-serif;background:#16141e;color:#ece8f8;"
    "display:grid;place-items:center;height:90vh'><div style='text-align:center'>"
    "<h2>{title}</h2><p>{body}</p></div></body>"
)


class _Callback:
    def __init__(self):
        self.result: asyncio.Future = asyncio.get_running_loop().create_future()
        self.server: Optional[asyncio.base_events.Server] = None
        self.port = 0

    async def start(self) -> None:
        for port in (PREFERRED_PORT, 0):
            try:
                self.server = await asyncio.start_server(self._handle, "127.0.0.1", port)
                self.port = self.server.sockets[0].getsockname()[1]
                return
            except OSError:
                continue
        raise SignInError("Couldn't open a local port for the sign-in callback.")

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}{CALLBACK_PATH}"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin-1")
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass                                    # skip headers
            parts = request_line.split()
            target = urlparse(parts[1]) if len(parts) >= 2 else None
            if target is None or target.path != CALLBACK_PATH:
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            query = {k: v[0] for k, v in parse_qs(target.query).items()}
            ok = "code" in query
            page = _DONE_PAGE.format(
                title="You're signed in" if ok else "Sign-in didn't finish",
                body="You can close this tab and go back to Fizzy." if ok else "You can close this tab.")
            body = page.encode("utf-8")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                         + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            if not self.result.done():
                self.result.set_result(query)
        except Exception:
            log.debug("bad callback request", exc_info=True)
        finally:
            try:
                await writer.drain()
            finally:
                writer.close()

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()


# ── sign-in, refresh, sign-out ──────────────────────────────────────────

async def sign_in(open_browser=webbrowser.open) -> ChatGPTSession:
    sess = load()
    save(sess)      # pins this PC's ext_agent_host_id before it's first sent
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    cb = _Callback()
    await cb.start()
    try:
        url = authorize_url(sess, cb.redirect_uri, state, nonce, challenge)
        open_browser(url)
        try:
            query = await asyncio.wait_for(cb.result, SIGN_IN_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise SignInError("Sign-in timed out. Try again from Tray → Keys and sign-in.") from None
    finally:
        await cb.close()

    if query.get("state") != state:
        raise SignInError("The sign-in reply didn't match this request, so it was ignored. Try again.")
    if query.get("error"):
        if query["error"] == "access_denied":
            raise SignInError("Sign-in was cancelled.")
        raise SignInError(f"Sign-in failed: {query.get('error_description') or query['error']}")

    issued = query.get("client_id")
    if sess.client_id and issued and issued != sess.client_id:
        raise SignInError("OpenAI answered with a different app registration than the saved one. Try again.")
    client_id = sess.client_id or issued
    if not client_id:
        raise SignInError("OpenAI didn't return an app registration. Try again.")

    tokens = await _token_request({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": query.get("code", ""),
        "code_verifier": verifier,
        "redirect_uri": cb.redirect_uri,
        "resource": RESOURCE,
    })
    claims = await verify_id_token(tokens["id_token"], client_id, nonce)

    sess.client_id = client_id
    sess.subject = claims["sub"]
    sess.email = claims.get("email", "")
    _apply_tokens(sess, tokens)
    save(sess)
    if not sess.plan_enabled:
        raise SignInError("You signed in, but didn't allow Fizzy to use your ChatGPT plan. "
                          "Sign in again and approve plan usage, or use an OpenAI API key instead.")
    log.info("signed in to ChatGPT as %s", sess.email or sess.subject)
    return sess


_refresh_lock = asyncio.Lock()


async def access_token() -> str:
    """A current access token, refreshed if it's about to expire."""
    async with _refresh_lock:          # refresh tokens rotate; never race two refreshes
        sess = load()
        if not sess.signed_in:
            raise SignInNeeded("Sign in with ChatGPT first (Tray → Keys and sign-in).")
        if time.time() < sess.expires_at - REFRESH_MARGIN_S:
            return sess.access_token
        try:
            tokens = await _token_request({
                "grant_type": "refresh_token",
                "client_id": sess.client_id,
                "refresh_token": sess.refresh_token,
                "resource": RESOURCE,
            })
        except SignInError as e:
            if getattr(e, "code", "") in TERMINAL_REFRESH_ERRORS:
                sess.clear_tokens()
                save(sess)
                raise SignInNeeded("Your ChatGPT sign-in has expired. Sign in again from the tray.") from e
            raise
        if tokens.get("id_token"):
            claims = await verify_id_token(tokens["id_token"], sess.client_id, None)
            if claims["sub"] != sess.subject:
                raise SignInError("The refreshed sign-in belongs to a different account.")
        _apply_tokens(sess, tokens)
        save(sess)
        return sess.access_token


def sign_out() -> None:
    """Forget the tokens but keep the registration for next time."""
    sess = load()
    sess.clear_tokens()
    save(sess)


def _apply_tokens(sess: ChatGPTSession, tokens: dict) -> None:
    sess.access_token = tokens["access_token"]
    sess.refresh_token = tokens.get("refresh_token") or sess.refresh_token
    if tokens.get("id_token"):
        sess.id_token = tokens["id_token"]
    sess.expires_at = time.time() + int(tokens.get("expires_in", 3600))
    if tokens.get("scope"):
        sess.scopes = tokens["scope"]


async def _token_request(form: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URL, data=form, headers={"Accept": "application/json"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or "access_token" not in body:
        code = body.get("error", f"http_{r.status_code}")
        err = SignInError(f"OpenAI sign-in failed: {body.get('error_description') or code}")
        err.code = code
        raise err
    return body


# ── ID token verification ───────────────────────────────────────────────

_jwks_client = None


async def verify_id_token(token: str, client_id: str, nonce: Optional[str]) -> dict:
    return await asyncio.to_thread(_verify_sync, token, client_id, nonce)


def _verify_sync(token: str, client_id: str, nonce: Optional[str]) -> dict:
    import jwt
    global _jwks_client
    if _jwks_client is None:
        with httpx.Client(timeout=10) as c:
            meta = c.get(DISCOVERY).json()
        _jwks_client = jwt.PyJWKClient(meta["jwks_uri"], cache_keys=True)
    key = _jwks_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id, issuer=ISSUER,
                        options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    if nonce is not None and claims.get("nonce") != nonce:
        raise SignInError("The sign-in reply failed a security check (nonce). Try again.")
    return claims
