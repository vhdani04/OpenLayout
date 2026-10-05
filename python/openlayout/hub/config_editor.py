"""The config view's editor - Virtuoso's hierarchy editor. The design's instance tree, with the
view each instance is simulated with: its schematic, or its extracted (PEX) netlist. Set it per cell
(every instance) or per instance. An OLSim test whose design is this config simulates exactly what
Show Netlist shows.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .theme import C
from ..olsim.config import Config, ConfigError, Netlist, bind, counts, describe_pex, find_pex, resolve
from ..olsim.engine import clean_netlist, netlist_schematic

INHERIT = "(cell / default)"
CELL_INHERIT = "(default)"
VIEW_COLOR = {"schematic": C["ok"], "extracted": "#56b6c2", "error": C["fail"]}


class ConfigEditor(QMainWindow):
    saved = Signal()

    def __init__(self, path, workarea, parent=None, open_olsim=None):
        super().__init__(parent)
        self.path = Path(path)
        self.workarea = workarea
        self.open_olsim = open_olsim
        self.cfg = Config.load(self.path)
        self.cell = workarea.cell_for_path(self.path) if workarea else None
        self.readonly = bool(self.cell and self.cell.library.readonly)
        self.net = None
        self.body = ""
        self._pex = {}
        self._dirty = False
        self._loading = False
        self.resize(1000, 680)

        central = QWidget()
        lay = QVBoxLayout(central)
        top = QHBoxLayout()
        self.top_lib = QComboBox()
        self.top_cell = QComboBox()
        self.default = QComboBox()
        self.default.addItems(["schematic", "extracted where available"])
        self.default.setToolTip("The view of every instance without a cell or instance binding")
        rescan = QPushButton("Rescan")
        rescan.setToolTip("Netlist the top schematic again (after editing it) and look for new PEX netlists")
        rescan.clicked.connect(self.rescan)
        top.addWidget(QLabel("Top cell"))
        top.addWidget(self.top_lib)
        top.addWidget(self.top_cell)
        top.addWidget(QLabel("schematic    Default view"))
        top.addWidget(self.default)
        top.addStretch(1)
        top.addWidget(rescan)
        lay.addLayout(top)
        hint = QLabel("Which view each instance is simulated with. Extracted: the cell's latest PEX netlist "
                      "(run PEX on its layout first) - a leaf, nothing below it is simulated. An instance "
                      "binding beats its cell's binding, which beats the default.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {C['dim']}")
        lay.addWidget(hint)

        split = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["instance", "cell", "instance binding", "simulated as", "why"])
        self.tree.header().setSectionResizeMode(4, QHeaderView.Stretch)
        split.addWidget(self.tree)
        cells_box = QWidget()
        cl = QVBoxLayout(cells_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(QLabel("Cell bindings (every instance of the cell)"))
        self.cells = QTableWidget(0, 4)
        self.cells.setHorizontalHeaderLabels(["cell", "library", "binding", "extracted netlist"])
        self.cells.verticalHeader().setVisible(False)
        self.cells.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        cl.addWidget(self.cells)
        split.addWidget(cells_box)
        split.setSizes([400, 220])
        lay.addWidget(split, 1)

        buttons = QHBoxLayout()
        self.summary = QLabel()
        buttons.addWidget(self.summary, 1)
        show = QPushButton("Show Netlist…")
        show.setToolTip("The netlist OLSim will simulate, with these bindings")
        show.clicked.connect(self.show_netlist)
        buttons.addWidget(show)
        if open_olsim and self.cell:
            olsim = QPushButton("OLSim")
            olsim.clicked.connect(lambda: open_olsim(self.cell))
            buttons.addWidget(olsim)
        self.save_btn = QPushButton("Save")
        self.save_btn.setEnabled(not self.readonly)
        self.save_btn.clicked.connect(self.save)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)
        self.setCentralWidget(central)

        self._loading = True
        if workarea:
            self.top_lib.addItems([lb.name for lb in workarea.libraries()])
        self.top_lib.currentTextChanged.connect(self._lib_changed)
        self.top_lib.setCurrentText(self.cfg.top.get("lib", ""))
        self._lib_changed(self.top_lib.currentText())
        self.top_cell.setCurrentText(self.cfg.top.get("cell", ""))
        self.default.setCurrentIndex(1 if self.cfg.default == "extracted" else 0)
        self._loading = False
        self.top_cell.currentTextChanged.connect(self._top_changed)
        self.default.currentIndexChanged.connect(self._default_changed)
        self._title()
        self.rescan()

    # ---- state --------------------------------------------------------------------------------
    def _title(self):
        key = self.cell.key if self.cell else self.path.stem
        self.setWindowTitle(f"Config - {key}" + (" (read-only)" if self.readonly else "") + (" *" if self._dirty else ""))

    def _mark(self):
        if not self._loading:
            self._dirty = True
            self._title()

    def _lib_changed(self, lib):
        self.top_cell.blockSignals(True)
        self.top_cell.clear()
        if self.workarea and self.workarea.library(lib):
            self.top_cell.addItems([c.name for c in self.workarea.library(lib).cells() if c.view("schematic")])
        self.top_cell.blockSignals(False)
        if not self._loading:
            self._top_changed(self.top_cell.currentText())

    def _top_changed(self, cell):
        if self._loading or not cell:
            return
        self.cfg.top = {"lib": self.top_lib.currentText(), "cell": cell}
        self._mark()
        self.rescan()

    def _default_changed(self, i):
        self.cfg.default = "extracted" if i == 1 else "schematic"
        self._mark()
        self.refresh()

    # ---- the design -----------------------------------------------------------------------------
    def pex(self, cell):
        """(path, note) of a cell's PEX netlist, or the exception why there is none (cached)."""
        k = cell.lower()
        if k not in self._pex:
            key = self.cfg.cell_binding(cell)[0] or cell
            try:
                self._pex[k] = find_pex(self.workarea, key if "/" in key else cell)
            except ConfigError as e:
                self._pex[k] = e
        return self._pex[k]

    def rescan(self):
        """Netlist the top schematic and show its hierarchy."""
        self._pex = {}
        top = self.cfg.top
        lib = self.workarea.library(top.get("lib", "")) if self.workarea else None
        cell = lib.cell(top.get("cell", "")) if lib else None
        view = cell.view("schematic") if cell else None
        if view is None:
            self.net, self.body = None, ""
            self.summary.setText(f"no schematic {self.cfg.top_label}")
            self.refresh()
            return
        try:
            out = self.workarea.run_dir(self.cell or cell) / "config"
            self.body, _ = clean_netlist(netlist_schematic(view.path, out, self.workarea.root))
            self.net = Netlist(self.body)
        except Exception as e:
            self.net, self.body = None, ""
            self.summary.setText(f"could not netlist {self.cfg.top_label}: {e}")
        self.refresh()

    def refresh(self):
        """The tree and the cell table from the netlist and the bindings."""
        self.tree.clear()
        self.cells.setRowCount(0)
        if self.net is None:
            return
        resolved = resolve(self.net, self.cfg, self.pex, strict=False)

        def add(parent, node):
            cell, view, how = resolved[node.path]
            why = {"cell": f"cell binding ({self.cfg.cell_binding(cell)[0]})", "instance": "instance binding"}.get(how, how)
            it = QTreeWidgetItem(parent, [node.inst, node.cell, "", view or "-", why])
            it.setData(0, Qt.UserRole, node.path)
            it.setToolTip(0, node.path)
            if view:
                it.setForeground(3, QColor(VIEW_COLOR.get(view, C["text"])))
                combo = QComboBox()
                combo.addItems([INHERIT, "schematic", "extracted"])
                combo.setCurrentText(self.cfg.instance_binding(node.path) or INHERIT)
                combo.currentTextChanged.connect(lambda v, p=node.path: self._bind_instance(p, v))
                self.tree.setItemWidget(it, 2, combo)
            else:
                for col in range(5):
                    it.setForeground(col, QColor(C["dim"]))
            for ch in node.children:
                add(it, ch)
            return it

        for n in self.net.tree():
            add(self.tree, n).setExpanded(True)
        for col in (0, 1, 3):
            self.tree.resizeColumnToContents(col)
        self.tree.setColumnWidth(2, 150)

        cells = list(dict.fromkeys(c for c, v, _ in resolved.values()))
        for name in cells:
            r = self.cells.rowCount()
            self.cells.insertRow(r)
            lib = next((lb.name for lb in self.workarea.libraries() if lb.cell(name)), "") if self.workarea else ""
            self.cells.setItem(r, 0, QTableWidgetItem(name))
            self.cells.setItem(r, 1, QTableWidgetItem(lib or "-"))
            combo = QComboBox()
            combo.addItems([CELL_INHERIT, "schematic", "extracted"])
            combo.setCurrentText(self.cfg.cell_binding(name)[1] or CELL_INHERIT)
            combo.currentTextChanged.connect(lambda v, n=name, lb=lib: self._bind_cell(n, lb, v))
            self.cells.setCellWidget(r, 2, combo)
            got = self.pex(name)
            if isinstance(got, Exception):
                item = QTableWidgetItem(str(got))
                item.setForeground(QColor(C["dim"]))
            else:
                item = QTableWidgetItem(describe_pex(got[0]) + (f" - {got[1]}" if got[1] else ""))
            self.cells.setItem(r, 3, item)
        self.cells.resizeColumnsToContents()
        errors = [p for p, (_, v, _) in resolved.items() if v == "error"]
        self.summary.setText(f"{counts(resolved)}" + (f"   -   {len(errors)} binding(s) without a PEX netlist: "
                                                       f"{', '.join(errors[:4])}" if errors else ""))
        self.summary.setStyleSheet(f"color: {C['fail']}" if errors else "")

    def _bind_instance(self, path, view):
        if view == INHERIT:
            self.cfg.instances = {k: v for k, v in self.cfg.instances.items() if k.lower() != path.lower()}
        else:
            self.cfg.instances[path] = view
        self._mark()
        self.refresh()

    def _bind_cell(self, name, lib, view):
        key = self.cfg.cell_binding(name)[0]
        if key:
            del self.cfg.cells[key]
        if view != CELL_INHERIT:
            self.cfg.cells[f"{lib}/{name}" if lib else name] = view
        self._mark()
        self.refresh()

    # ---- actions --------------------------------------------------------------------------------
    def netlist(self) -> str:
        """The netlist OLSim simulates with these bindings (raises ConfigError)."""
        if self.net is None:
            raise ConfigError(self.summary.text() or "no design")

        def pex_for(cell):
            got = self.pex(cell)
            if isinstance(got, Exception):
                raise got
            return got

        text, notes, resolved = bind(self.body, self.cfg, pex_for)
        return "\n".join([f"* {self.cfg.top_label} - {counts(resolved)}"] + [f"* {n}" for n in notes]) + "\n" + text

    def show_netlist(self):
        try:
            text = self.netlist()
        except (ConfigError, OSError) as e:
            QMessageBox.warning(self, "Show Netlist", str(e))
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Netlist - {self.cfg.top_label} (config)")
        dlg.resize(820, 600)
        v = QVBoxLayout(dlg)
        ed = QPlainTextEdit(text, readOnly=True)
        ed.setFont(theme.mono_font())
        v.addWidget(ed)
        dlg.show()
        return dlg

    def save(self):
        if self.readonly:
            return False
        self.cfg.save(self.path)
        self._dirty = False
        self._title()
        self.saved.emit()
        return True

    def closeEvent(self, e):
        if self._dirty and not self.readonly:
            r = QMessageBox.question(self, "Config", f"Save the changes to {self.path.name}?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                e.ignore()
                return
            if r == QMessageBox.Save:
                self.save()
        super().closeEvent(e)
