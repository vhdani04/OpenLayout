"""CIW: the hub's log + command line (a command interpreter window, in Python)."""
import code
import contextlib
import html
import io
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from .theme import C, mono_font

LEVELS = {"info": ("*INFO*", C["accent"]), "ok": ("*INFO*", C["ok"]), "warn": ("*WARNING*", C["warn"]),
          "error": ("*Error*", C["fail"]), "cmd": ("", C["text"]), "out": ("", C["dim"])}


class HistoryLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.history, self.pos = [], 0

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.pos = len(self.history)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Down) and self.history:
            self.pos = max(0, self.pos - 1) if e.key() == Qt.Key_Up else min(len(self.history), self.pos + 1)
            self.setText(self.history[self.pos] if self.pos < len(self.history) else "")
            return
        super().keyPressEvent(e)


class CIW(QWidget):
    def __init__(self, namespace: dict):
        super().__init__()
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(mono_font())
        self.log.setMaximumBlockCount(10000)
        self.log.setUndoRedoEnabled(False)
        self.prompt = QLabel(">", objectName="prompt")
        self.input = HistoryLineEdit()
        self.input.setFont(mono_font())
        self.input.setPlaceholderText("Python command — try  help(ol)")
        self.input.returnPressed.connect(self._submit)
        self.interp = code.InteractiveInterpreter(namespace)
        self._buffer = []

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.prompt)
        row.addWidget(self.input)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 6)
        lay.setSpacing(4)
        lay.addWidget(self.log)
        lay.addLayout(row)

    # ---- output -----------------------------------------------------------------------------
    def write(self, level: str, message: str) -> None:
        tag, color = LEVELS.get(level, LEVELS["info"])
        stamp = f'<span style="color:{C["dim"]}">{time.strftime("%H:%M:%S")}</span> ' if tag else ""
        tag_html = f'<span style="color:{color};font-weight:600">{tag}</span> ' if tag else ""
        body_color = C["text"] if level in ("info", "ok", "warn", "error", "cmd") else C["dim"]
        lines = html.escape(message.rstrip("\n")).split("\n")
        body = "<br>".join(f'<span style="color:{body_color}">{ln or "&nbsp;"}</span>' for ln in lines)
        self.log.appendHtml(f'<div style="white-space:pre">{stamp}{tag_html}{body}</div>')
        self.log.moveCursor(QTextCursor.End)

    def info(self, msg): self.write("info", msg)
    def ok(self, msg): self.write("ok", msg)
    def warn(self, msg): self.write("warn", msg)
    def error(self, msg): self.write("error", msg)
    def output(self, text): self.write("out", text)

    # ---- command line -----------------------------------------------------------------------
    def _submit(self) -> None:
        text = self.input.text()
        self.input.remember(text)
        self.input.clear()
        self.write("cmd", ("... " if self._buffer else "> ") + text)
        self._buffer.append(text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            more = self.interp.runsource("\n".join(self._buffer), "<ciw>")
        if not more:
            self._buffer = []
        self.prompt.setText("..." if more else ">")
        if out.getvalue():
            self.output(out.getvalue())
