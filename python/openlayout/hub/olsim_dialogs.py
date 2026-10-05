"""OLSim's dialogs: picking signals on the schematic in xschem. (The views each cell simulates
with are the config view's - hub/config_editor.py.)
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPushButton, QVBoxLayout

from ..tools import XschemBridge
from ..workarea import WorkareaError

TCL_LIST_RE = re.compile(r"\{([^{}]*)\}|(\S+)")


def tcl_list(text: str) -> list[str]:
    return [a or b for a, b in TCL_LIST_RE.findall(text or "")]


class AttachedXschem(XschemBridge):
    """The hub's xschem (its port from the workarea session): used, never started a second time."""

    def __init__(self, workarea, port):
        super().__init__(workarea)
        self.port = int(port)

    @property
    def running(self):
        try:
            self.ping(1.0)
            return True
        except OSError:
            return False

    def start(self):
        raise WorkareaError("the hub's xschem is not running")


class SchematicPicker(QDialog):
    """Signals picked on the testbench in xschem: every net, label, pin or source selected there is
    added as a plotted output (sources: their current)."""

    def __init__(self, parent, bridge, add_output, have=()):
        super().__init__(parent)
        self.setWindowTitle("Select on Schematic")
        self.setModal(False)
        self.resize(420, 320)
        self.bridge = bridge
        self.add_output = add_output
        self.added = set(have)
        self.seen = set()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Click nets, labels, pins or voltage sources in xschem (Shift adds to the\n"
                             "selection). Each one is added to the outputs and plotted after the run."))
        self.list = QListWidget()
        lay.addWidget(self.list)
        done = QPushButton("Done")
        done.clicked.connect(self.close)
        lay.addWidget(done)
        self.timer = QTimer(self, interval=600, timeout=self.poll)

    def start(self, view=None, path=None):
        self.bridge.ensure_started()
        if view is not None:
            self.bridge.open(view)
        elif path:
            self.bridge.send(f"xschem load {{{Path(path).as_posix()}}}")
        self.show()
        self.timer.start()

    def selection(self) -> list[tuple[str, str]]:
        """[(name, expression)] of what is selected in xschem now."""
        out = []
        self.bridge.send("xschem rebuild_connectivity", timeout=5)
        for lab in tcl_list(self.bridge.send("xschem selected_wire", timeout=5)):
            if lab:
                net = lab.lstrip("#")
                out.append((net, f'v("{net}")'))
        for inst in tcl_list(self.bridge.send("xschem selected_set", timeout=5)):
            lab = self.bridge.send(f"xschem getprop instance {{{inst}}} lab", timeout=5).strip()
            if lab:
                net = lab.lstrip("#")
                out.append((net, f'v("{net}")'))
            elif inst.upper().startswith("V"):
                out.append((f"i_{inst}", f'i("{inst}")'))
        return out

    def poll(self):
        try:
            picked = self.selection()
        except OSError:
            return                                   # xschem busy or closing: next time
        for name, expr in picked:
            if expr in self.seen:
                continue
            self.seen.add(expr)
            if expr in self.added:                   # say so - a click should never seem to do nothing
                self.list.addItem(f"{name}    {expr}    (already an output)")
                continue
            self.added.add(expr)
            self.add_output(expr, name)
            self.list.addItem(f"{name}    {expr}    added")

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)
