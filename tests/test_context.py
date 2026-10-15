import asyncio

import pytest

from fizzy.ai.base import Image
from fizzy.context import gather as gather_mod
from fizzy.context import privacy, selection
from fizzy.context.screen import Monitor, Shot
from fizzy.context.window import WindowInfo
from fizzy.settings import CONTEXT_SCREEN, CONTEXT_SELECTION_ONLY, CONTEXT_SELECTION_OR_SCREEN, Settings

WIN = WindowInfo(1, "Report.docx - Word", "winword.exe", 42)


@pytest.fixture
def fake_capture(monkeypatch):
    calls = []

    async def shots(_settings):
        calls.append(1)
        return [Shot(Monitor(1, 0, 0, 100, 100, 0, 0, 1.0), Image("x", 10, 10), None)]

    monkeypatch.setattr(gather_mod, "_screenshots", shots)
    return calls


def run(mode, selection_text=None, pointing=False, vision=True, win=WIN):
    s = Settings()
    s.screen_context = mode
    return asyncio.run(gather_mod.gather(s, win, vision=vision, selection=selection_text, pointing=pointing))


@pytest.mark.parametrize("mode, sel, pointing, shots, keeps_sel", [
    (CONTEXT_SCREEN, "text", False, 1, False),
    (CONTEXT_SELECTION_OR_SCREEN, "text", False, 0, True),
    (CONTEXT_SELECTION_OR_SCREEN, None, False, 1, False),
    (CONTEXT_SELECTION_ONLY, None, False, 0, False),
    (CONTEXT_SELECTION_ONLY, "text", True, 1, True),     # pointing needs the picture
])
def test_screen_context_modes(fake_capture, mode, sel, pointing, shots, keeps_sel):
    ctx = run(mode, sel, pointing)
    assert len(ctx.shots) == shots
    assert (ctx.selection is not None) == keeps_sel


def test_text_only_model_gets_no_screenshot(fake_capture):
    assert run(CONTEXT_SCREEN, vision=False).shots == []


def test_sensitive_window_sends_nothing(fake_capture):
    win = WindowInfo(1, "Sign in to your bank", "chrome.exe", 1)
    ctx = run(CONTEXT_SCREEN, "secret", win=win)
    assert ctx.sensitive and ctx.shots == [] and ctx.selection is None
    assert not fake_capture


@pytest.mark.parametrize("title, exe, sensitive", [
    ("Vault — 1Password", "1password.exe", True),
    ("Checkout | Shop", "chrome.exe", True),
    ("Quarterly report.xlsx - Excel", "excel.exe", False),
])
def test_privacy(title, exe, sensitive):
    assert privacy.is_sensitive(WindowInfo(1, title, exe, 1)) is sensitive


def test_selection_cleaning():
    assert selection.clean("  \r\n ") is None
    long = selection.clean("a" * 20_000)
    assert len(long) < 12_100 and long.endswith("cut short]")


def test_no_copy_fallback_in_terminals():
    assert not selection.clipboard_allowed(WindowInfo(1, "PowerShell", "windowsterminal.exe", 1))
    assert selection.clipboard_allowed(WIN)


def test_compose_question():
    assert gather_mod.compose_question("Explain", None) == "Explain"
    assert '"""\nhello\n"""' in gather_mod.compose_question("Explain", "hello")
