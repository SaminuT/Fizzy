"""Enter API keys and manage sign-ins. Keys go straight to Windows Credential Manager."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from fizzy import APP_NAME
from fizzy.settings import Settings, get_secret, set_secret

KEY_FIELDS = [
    ("anthropic_api_key", "Anthropic (Claude)", "sk-ant-…"),
    ("openai_api_key", "OpenAI", "sk-…"),
    ("gemini_api_key", "Google Gemini", "AIza…"),
    ("deepgram_api_key", "Deepgram (speech-to-text)", ""),
    ("elevenlabs_api_key", "ElevenLabs (voice)", ""),
    ("elevenlabs_voice_id", "ElevenLabs voice ID", "optional"),
]


class KeysDialog(QDialog):
    saved = pyqtSignal()
    sign_in_requested = pyqtSignal(str)     # "chatgpt" | "copilot"
    sign_out_requested = pyqtSignal(str)

    def __init__(self, settings: Settings, sign_ins: dict[str, tuple[str, bool]] | None = None, parent=None):
        """sign_ins: {id: (label, signed_in)} for the account sign-ins on offer."""
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(f"{APP_NAME} — Keys and sign-in")
        self.setMinimumWidth(460)
        self._edits: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)

        if sign_ins:
            box = QGroupBox("Sign in instead of a key")
            col = QVBoxLayout(box)
            for sid, (label, signed_in) in sign_ins.items():
                row = QHBoxLayout()
                row.addWidget(QLabel(f"{label}: {'signed in' if signed_in else 'not signed in'}"), stretch=1)
                btn = QPushButton("Sign out" if signed_in else "Sign in")
                if signed_in:
                    btn.clicked.connect(lambda _c, s=sid: (self.sign_out_requested.emit(s), self.accept()))
                else:
                    btn.clicked.connect(lambda _c, s=sid: (self.sign_in_requested.emit(s), self.accept()))
                row.addWidget(btn)
                col.addLayout(row)
            root.addWidget(box)

        keys = QGroupBox("API keys (stored in Windows Credential Manager)")
        form = QFormLayout(keys)
        for name, label, hint in KEY_FIELDS:
            e = QLineEdit()
            e.setEchoMode(QLineEdit.EchoMode.Password if "key" in name else QLineEdit.EchoMode.Normal)
            e.setPlaceholderText("saved — type to replace" if get_secret(name) else hint)
            form.addRow(label, e)
            self._edits[name] = e
        root.addWidget(keys)

        servers = QGroupBox("Servers")
        sform = QFormLayout(servers)
        self.base_url = QLineEdit(settings.openai_base_url)
        self.base_url.setPlaceholderText("blank = api.openai.com")
        sform.addRow("OpenAI-compatible URL", self.base_url)
        self.ollama = QLineEdit(settings.ollama_host)
        sform.addRow("Ollama", self.ollama)
        self.lmstudio = QLineEdit(settings.lmstudio_host)
        sform.addRow("LM Studio", self.lmstudio)
        root.addWidget(servers)

        clear = QLabel("To remove a saved key, type a single space and save.")
        clear.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(clear)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self) -> None:
        for name, e in self._edits.items():
            text = e.text()
            if text == " ":
                set_secret(name, None)
            elif text.strip():
                set_secret(name, text.strip())
        self.settings.openai_base_url = self.base_url.text().strip()
        self.settings.ollama_host = self.ollama.text().strip() or Settings.ollama_host
        self.settings.lmstudio_host = self.lmstudio.text().strip() or Settings.lmstudio_host
        self.settings.save()
        self.saved.emit()
        self.accept()
