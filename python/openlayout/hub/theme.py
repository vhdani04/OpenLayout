"""OpenLayout look: dark Fusion palette, colors shared with the tool themes, generated icons."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

C = {
    "window": "#1f2329", "panel": "#262b33", "base": "#181b20", "alt": "#1d2127", "border": "#323843",
    "text": "#d9dee7", "dim": "#7d8696", "accent": "#4fa3ff", "select": "#2c5d94",
    "ok": "#4cc38a", "fail": "#ef6b6b", "warn": "#e8b04b",
}
VIEW_COLORS = {"schematic": "#4cc38a", "symbol": "#e8b04b", "layout": "#4fa3ff", "netlist": "#9aa3b2"}
VIEW_LETTERS = {"schematic": "S", "symbol": "Y", "layout": "L", "netlist": "N"}
ICON_FILE = Path(__file__).resolve().parents[3] / "share" / "icons" / "openlayout.svg"

QSS = f"""
QToolBar {{ background: {C['panel']}; border: none; border-bottom: 1px solid {C['border']}; padding: 3px; spacing: 2px; }}
QToolButton {{ padding: 4px 8px; border-radius: 4px; }}
QToolButton:hover {{ background: {C['border']}; }}
QToolButton:disabled {{ color: {C['dim']}; }}
QStatusBar {{ background: {C['panel']}; border-top: 1px solid {C['border']}; }}
QListWidget, QPlainTextEdit, QTextBrowser, QLineEdit, QComboBox {{
    background: {C['base']}; border: 1px solid {C['border']}; border-radius: 4px; }}
QListWidget::item {{ padding: 2px 4px; }}
QListWidget::item:selected {{ background: {C['select']}; color: white; }}
QLabel#columnTitle {{ color: {C['dim']}; font-weight: 600; padding: 4px 2px 2px 2px; }}
QLabel#prompt {{ color: {C['accent']}; font-family: monospace; font-weight: 700; }}
QSplitter::handle {{ background: {C['window']}; }}
QMenu::item:disabled {{ color: {C['dim']}; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    for role, key in [(QPalette.Window, "window"), (QPalette.Base, "base"), (QPalette.AlternateBase, "alt"),
                      (QPalette.Button, "panel"), (QPalette.ToolTipBase, "panel"), (QPalette.Text, "text"),
                      (QPalette.WindowText, "text"), (QPalette.ButtonText, "text"), (QPalette.ToolTipText, "text"),
                      (QPalette.Highlight, "select"), (QPalette.Link, "accent")]:
        p.setColor(role, QColor(C[key]))
    p.setColor(QPalette.HighlightedText, Qt.white)
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(C["dim"]))
    app.setPalette(p)
    app.setStyleSheet(QSS)
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))


def mono_font() -> QFont:
    f = QFont("DejaVu Sans Mono")
    f.setStyleHint(QFont.Monospace)
    f.setPointSize(10)
    return f


def _chip(p: QPainter, x: float, letter: str, color: str, on: bool, h: int) -> None:
    rect = QRectF(x, 1, h - 2, h - 2)
    c = QColor(color if on else C["border"])
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(rect, 3, 3)
    p.setPen(QColor("#10131a") if on else QColor(C["dim"]))
    f = p.font()
    f.setBold(True)
    f.setPixelSize(h - 6)
    p.setFont(f)
    p.drawText(rect, Qt.AlignCenter, letter)


def _icon(pm: QPixmap) -> QIcon:
    """Same pixmap for normal and selected states (Qt would otherwise tint selected rows)."""
    icon = QIcon()
    icon.addPixmap(pm, QIcon.Normal)
    icon.addPixmap(pm, QIcon.Selected)
    return icon


def view_icon(view_name: str, size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    _chip(p, 1, VIEW_LETTERS.get(view_name, "?"), VIEW_COLORS.get(view_name, C["dim"]), True, size)
    p.end()
    return _icon(pm)


def cell_icon(views: set, status: dict, h: int = 16) -> QIcon:
    """Row of view chips (S Y L, dim when missing) followed by a run-status dot."""
    names = ["schematic", "symbol", "layout"]
    pm = QPixmap(len(names) * h + 12, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    for i, n in enumerate(names):
        _chip(p, i * h, VIEW_LETTERS[n], VIEW_COLORS[n], n in views, h)
    results = [s["ok"] for s in status.values()]
    if results:
        color = C["ok"] if all(results) else C["fail"]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(len(names) * h + 3, h / 2 - 4, 8, 8))
    p.end()
    return _icon(pm)


def library_icon(readonly: bool, size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    color = QColor(C["dim"] if readonly else C["accent"])
    p.setPen(QPen(color, 1.5))
    p.setBrush(Qt.NoBrush)
    for i in range(3):  # stacked "layers"
        p.drawRoundedRect(QRectF(2 + i * 1.5, 3 + i * 3.2, size - 7, 4), 1.5, 1.5)
    if readonly:
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(size - 7, size - 7, 6, 5), 1, 1)
    p.end()
    return _icon(pm)


def dot_pixmap(color: str, size: int = 10) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    p.end()
    return pm
