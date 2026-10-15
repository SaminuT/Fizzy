import asyncio
import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from fizzy.ai import chatgpt_auth as auth


def test_pkce_challenge_matches_verifier():
    verifier, challenge = auth.pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert 43 <= len(verifier) <= 128


def test_first_sign_in_registers():
    s = auth.ChatGPTSession()
    q = parse_qs(urlparse(auth.authorize_url(s, "http://127.0.0.1:1455/auth/callback", "st", "no", "ch")).query)
    assert q["client_id"] == [auth.REGISTRATION_CLIENT]
    assert q["agent_name_hint"] == ["Fizzy"]
    assert "chatgpt.tokens.use.direct" in q["scope"][0].split()
    assert q["resource"] == ["https://api.openai.com/v1"]
    assert "id_token_hint" not in q


def test_reauthorisation_reuses_registration():
    s = auth.ChatGPTSession(client_id="oaiapp_1", id_token="tok", email="a@b.c")
    q = parse_qs(urlparse(auth.authorize_url(s, "http://127.0.0.1:1/auth/callback", "st", "no", "ch")).query)
    assert q["client_id"] == ["oaiapp_1"]
    assert q["id_token_hint"] == ["tok"] and q["login_hint"] == ["a@b.c"]
    assert "agent_name_hint" not in q
    assert q["ext_agent_host_id"] == [s.ext_agent_host_id]


def test_callback_listener_captures_query():
    async def go():
        cb = auth._Callback()
        await cb.start()
        async with httpx.AsyncClient() as h:
            r = await h.get(cb.redirect_uri + "?code=abc&state=st")
        await cb.close()
        return r.status_code, cb.result.result()

    status, query = asyncio.run(go())
    assert status == 200 and query == {"code": "abc", "state": "st"}


def test_access_token_still_valid_is_returned_as_is():
    auth.save(auth.ChatGPTSession(client_id="c", access_token="A", refresh_token="R",
                                  expires_at=time.time() + 3600, scopes=auth.PLAN_SCOPE))
    assert asyncio.run(auth.access_token()) == "A"


def test_expiring_token_is_refreshed_and_rotated(monkeypatch):
    auth.save(auth.ChatGPTSession(client_id="c", access_token="old", refresh_token="R1",
                                  expires_at=time.time() + 10, scopes=auth.PLAN_SCOPE))
    seen = {}

    async def fake_token_request(form):
        seen.update(form)
        return {"access_token": "new", "refresh_token": "R2", "expires_in": 3600}

    monkeypatch.setattr(auth, "_token_request", fake_token_request)
    assert asyncio.run(auth.access_token()) == "new"
    assert seen["grant_type"] == "refresh_token" and seen["client_id"] == "c" and seen["refresh_token"] == "R1"
    assert "scope" not in seen
    assert auth.load().refresh_token == "R2"


def test_dead_refresh_token_asks_for_sign_in(monkeypatch):
    auth.save(auth.ChatGPTSession(client_id="c", access_token="old", refresh_token="R1",
                                  expires_at=0, scopes=auth.PLAN_SCOPE))

    async def fail(_form):
        e = auth.SignInError("nope")
        e.code = "refresh_token_reused"
        raise e

    monkeypatch.setattr(auth, "_token_request", fail)
    with pytest.raises(auth.SignInNeeded):
        asyncio.run(auth.access_token())
    left = auth.load()
    assert not left.signed_in and left.client_id == "c"     # registration kept


def test_sign_out_keeps_registration():
    auth.save(auth.ChatGPTSession(client_id="c", access_token="A", refresh_token="R"))
    host = auth.load().ext_agent_host_id
    auth.sign_out()
    s = auth.load()
    assert not s.signed_in and s.client_id == "c" and s.ext_agent_host_id == host
