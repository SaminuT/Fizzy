# Fizzy

**An AI helper that sits beside your cursor on Windows.**

Ask Fizzy about whatever you're doing: an app you're learning, an error on screen, a paragraph you've highlighted. Talk to it or type. It looks at your screen (or just the text you highlighted), answers out loud and in a small panel, and flies over to point at the button you asked about.

## What it does

- **Ask by voice or by typing.** Hold the hotkey and talk, or tap it, talk, and Fizzy answers when you pause. The panel has a typing box too. Optionally, say **"Fizzy"** to start hands-free.
- **Sees what you see.** Each question can include a screenshot of the monitor your pointer is on, the active window's name, and where your pointer is.
- **Or just the text you highlighted.** With the *Screen context* setting, Fizzy sends your highlighted text instead of a screenshot. That's faster, cheaper and more private. It still takes a screenshot when you ask where something is.
- **Points at things.** "Where's the export button?" sends the buddy gliding to it. Fizzy finds targets through Windows UI Automation first (exact), then on-screen text recognition, then a grid the AI reads.
- **Walks you through steps.** Long instructions are read one step at a time. Say "next" to continue, or "repeat" to hear the last one again.
- **Private by default.** Fizzy never captures password managers, banking or sign-in windows. Its own windows are left out of every screenshot. The microphone is only open while you're asking something, unless you turn on the wake word.

## AI providers

Switch any time from **Tray → AI**.

| Provider | How to connect |
|---|---|
| Claude | Anthropic API key |
| OpenAI | OpenAI API key, or any OpenAI-compatible server URL |
| **ChatGPT** | **Sign in with ChatGPT.** Uses your ChatGPT plan instead of an API key |
| Gemini | Google AI Studio API key |
| GitHub Copilot | Sign in with GitHub (device code) |
| Ollama | Runs on your PC. No account needed |
| LM Studio | Runs on your PC. No account needed |

Keys and sign-ins are stored in **Windows Credential Manager**, never in a plain file. Add them under **Tray → Keys and sign-in**.

Speech works offline by default: local Whisper for listening and free Microsoft Edge voices for speaking. OpenAI, Deepgram or ElevenLabs keys switch to those services instead.

## Run from source

Needs Windows 10 (2004 or later) or Windows 11, and Python 3.11 or newer.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m fizzy
```

Fizzy starts in the system tray. Hotkeys:

- **Ctrl + Alt + Space**: talk (hold it, or tap and speak).
- **Ctrl + Alt + T**: show or hide the panel, ready to type. Text you've highlighted in your app comes along.
- **Esc**: stop an answer, or close the panel when it's idle.

Both hotkeys can be changed under **Tray → Voice and microphone**.

The first voice question downloads a small Whisper model. The first pointing question can take a few extra seconds while the text-recognition model loads.

## Settings

Most options are in the tray menu. Everything is saved to `%LOCALAPPDATA%\Fizzy\settings.json`. Any setting can be overridden for a single run with an environment variable named `FIZZY_<SETTING>`, for example:

```powershell
$env:FIZZY_PROVIDER = "ollama"; python -m fizzy
```

Logs are in `%LOCALAPPDATA%\Fizzy\fizzy.log` (**Tray → Open data folder**).

## Tests

```powershell
pip install pytest
python -m pytest
```

## Contact

Report problems at [github.com/Owask/Fizzy/issues](https://github.com/Owask/Fizzy/issues), or email saminuhansaja.w@gmail.com.
