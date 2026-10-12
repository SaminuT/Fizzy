"""User settings (settings.json) and secrets (Windows Credential Manager).

Plain settings live in %LOCALAPPDATA%\\Fizzy\\settings.json. Anything that
grants access to an account (API keys, sign-in tokens) goes to the OS
credential store through `keyring` and never touches that file.

Any setting can be overridden for one run with an environment variable named
FIZZY_<FIELD> in upper case, e.g. FIZZY_PROVIDER=ollama.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

from fizzy.paths import data_dir

log = logging.getLogger(__name__)

KEYRING_SERVICE = "Fizzy"

# What gets sent along with a question.
CONTEXT_SCREEN = "screen"                      # always a screenshot
CONTEXT_SELECTION_OR_SCREEN = "selection_or_screen"  # highlighted text if any, else screenshot
CONTEXT_SELECTION_ONLY = "selection_only"      # never an image
CONTEXT_MODES = (CONTEXT_SCREEN, CONTEXT_SELECTION_OR_SCREEN, CONTEXT_SELECTION_ONLY)


@dataclass
class Settings:
    provider: str = "ollama"
    # Model picked per provider, e.g. {"anthropic": "claude-sonnet-5-5"}.
    models: dict = field(default_factory=dict)

    hotkey: str = "ctrl+alt+space"
    hold_threshold_s: float = 0.5   # held longer than this = hold-to-talk

    screen_context: str = CONTEXT_SELECTION_OR_SCREEN
    all_monitors: bool = False      # False = only the monitor the pointer is on
    clipboard_fallback: bool = True
    privacy_guard: bool = True

    speak_typed: bool = True        # read answers to typed questions aloud too
    show_buddy: bool = True
    wake_word: bool = False

    mic_device: Optional[int] = None
    stt: str = "auto"               # auto | local | openai | deepgram
    whisper_model: str = "base"
    tts: str = "auto"               # auto | edge | openai | elevenlabs
    voice: str = ""                 # provider-specific voice name; "" = default

    openai_base_url: str = ""       # any OpenAI-compatible server
    ollama_host: str = "http://127.0.0.1:11434"
    lmstudio_host: str = "http://127.0.0.1:1234/v1"

    # ── persistence ─────────────────────────────────────────────────────

    @staticmethod
    def path() -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        p = cls.path()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                known = {f.name for f in fields(cls)}
                for k, v in raw.items():
                    if k in known:
                        setattr(s, k, v)
            except Exception:
                log.exception("settings.json is unreadable; using defaults")
        s._apply_env()
        if s.screen_context not in CONTEXT_MODES:
            s.screen_context = CONTEXT_SELECTION_OR_SCREEN
        return s

    def save(self) -> None:
        p = self.path()
        data = json.dumps(asdict(self), indent=2)
        # Write-then-rename so a crash mid-write can't leave a half file.
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".settings-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _apply_env(self) -> None:
        for f in fields(self):
            raw = os.environ.get(f"FIZZY_{f.name.upper()}")
            if raw is None or f.name == "models":
                continue
            current = getattr(self, f.name)
            try:
                if isinstance(current, bool):
                    value = raw.strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(current, int) and not isinstance(current, bool):
                    value = int(raw)
                elif isinstance(current, float):
                    value = float(raw)
                elif current is None and f.name == "mic_device":
                    value = int(raw) if raw.strip() else None
                else:
                    value = raw
            except ValueError:
                log.warning("ignoring FIZZY_%s=%r: wrong type", f.name.upper(), raw)
                continue
            setattr(self, f.name, value)

    # ── helpers ─────────────────────────────────────────────────────────

    def model_for(self, provider: str) -> Optional[str]:
        return self.models.get(provider) or None

    def set_model(self, provider: str, model: str) -> None:
        self.models[provider] = model


# ── secrets ─────────────────────────────────────────────────────────────

# Secret name → environment variable that may provide it instead.
SECRET_ENV = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "deepgram_api_key": "DEEPGRAM_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
}


# Windows Credential Manager caps one entry at 2560 bytes of UTF-16, and a
# sign-in token bundle is bigger than that. Long values are stored as parts:
# "<name>" holds "parts:N", and "<name>#0" … "<name>#N-1" hold the pieces.
_PART_CHARS = 1000
_PARTS_PREFIX = "parts:"


def get_secret(name: str) -> Optional[str]:
    env = SECRET_ENV.get(name)
    if env and os.environ.get(env):
        return os.environ[env]
    try:
        import keyring
        head = keyring.get_password(KEYRING_SERVICE, name)
        if head and head.startswith(_PARTS_PREFIX):
            count = int(head[len(_PARTS_PREFIX):])
            pieces = [keyring.get_password(KEYRING_SERVICE, f"{name}#{i}") for i in range(count)]
            if any(p is None for p in pieces):
                log.warning("secret %s is missing parts", name)
                return None
            return "".join(pieces)
        return head or None
    except Exception:
        log.exception("could not read %s from the credential store", name)
        return None


def set_secret(name: str, value: Optional[str]) -> None:
    import keyring
    _delete_secret(name)
    if not value:
        return
    if len(value) <= _PART_CHARS:
        keyring.set_password(KEYRING_SERVICE, name, value)
        return
    pieces = [value[i:i + _PART_CHARS] for i in range(0, len(value), _PART_CHARS)]
    for i, piece in enumerate(pieces):
        keyring.set_password(KEYRING_SERVICE, f"{name}#{i}", piece)
    keyring.set_password(KEYRING_SERVICE, name, f"{_PARTS_PREFIX}{len(pieces)}")


def _delete_secret(name: str) -> None:
    import keyring
    head = keyring.get_password(KEYRING_SERVICE, name)
    if head and head.startswith(_PARTS_PREFIX):
        for i in range(int(head[len(_PARTS_PREFIX):])):
            try:
                keyring.delete_password(KEYRING_SERVICE, f"{name}#{i}")
            except keyring.errors.PasswordDeleteError:
                pass
    if head is not None:
        try:
            keyring.delete_password(KEYRING_SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass


def get_json_secret(name: str) -> Optional[dict]:
    raw = get_secret(name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def set_json_secret(name: str, value: Optional[dict]) -> None:
    set_secret(name, json.dumps(value) if value else None)
