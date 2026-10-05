"""OLSim's dialogs: the hierarchy (which view each cell of a testbench simulates with - its
schematic or its extracted netlist, like a config view) and picking signals on the schematic in
xschem.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHeaderView, QLabel, QListWidget,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..olsim.engine import OLSimError, Run
from ..olsim.setup import Test

TCL_LIST_RE = re.compile(r"\{([^{}]*)\}|(\S+)")


def tcl_list(text: str) -> list[str]:
    return [a or b for a, b in TCL_LIST_RE.findall(text or "")]


def testbench_cells(run: Run, test: Test) -> list[str]:
    """The subcircuits a test's testbench instantiates (the cells of its hierarchy)."""
    plain = Test(**{**test.__dict__, "extracted": []})
    body, _, _ = run._netlist(plain)
    return list(dict.fromkeys(re.findall(r"(?im)^\s*\.subckt\s+(\S+)", body)))


class HierarchyDialog(QDialog):
    """Per cell of the testbench: simulate its schematic, or its extracted (PEX) netlist."""

    def __init__(self, parent, run: Run, test: Test, workarea):
        super().__init__(parent)
        self.setWindowTitle(f"Hierarchy - test {test.name}")
        self.resize(820, 360)
        self.workarea = workarea
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Which view each cell of the testbench is simulated with. Extracted: the cell's "
                             "latest PEX netlist (run PEX on its layout first)."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["cell", "library", "view", "extracted netlist"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        lay.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        chosen = {e.split("/")[-1].split(".")[0] for e in test.extracted}
        self.rows = []
        for name in testbench_cells(run, test):
            lib = next((lb.name for lb in (workarea.libraries() if workarea else [])
                        if lb.cell(name) and lb.cell(name).view("schematic")), "")
            entry = f"{lib}/{name}" if lib else name
            try:
                pex, _, note = run._pex_netlist(entry)
                when = datetime.datetime.fromtimestamp(pex.stat().st_mtime).strftime("%b %d %H:%M")
                status, available = f"{pex}  ({when})" + (f" - {note}" if note else ""), True
            except OLSimError as e:
                status, available = str(e), False
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(lib or "-"))
            combo = QComboBox()
            combo.addItems(["schematic", "extracted"])
            if not available:
                combo.model().item(1).setEnabled(False)
            combo.setCurrentIndex(1 if name in chosen and available else 0)
            self.table.setCellWidget(r, 2, combo)
            self.table.setItem(r, 3, QTableWidgetItem(status))
            self.rows.append((entry, combo))
        if not self.rows:
            self.table.insertRow(0)
            self.table.setItem(0, 0, QTableWidgetItem("(the testbench instantiates no subcircuits)"))
        self.table.resizeColumnsToContents()

    def extracted(self) -> list[str]:
        return [entry for entry, combo in self.rows if combo.currentText() == "extracted"]


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
            if expr in self.added:
                continue
            self.added.add(expr)
            self.add_output(expr, name)
            self.list.addItem(f"{name}    {expr}")

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)
