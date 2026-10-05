"""The OLSim (OpenLayoutSim) window: one setup - tests, design variables, corners,
outputs with specs - run with ngspice in parallel, results as a table of outputs x points
(pass / fail coloured), waveforms in the viewer (waves.py).

    openlayout olsim [setup.olsim | <lib> <cell>]      (also: the hub, a cell's olsim view)
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDockWidget,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..olsim.calc import fmt, guess_unit, si, variable_unit
from ..olsim.engine import History, Run, delete_history, design_variables, histories
from ..olsim.setup import (ANALYSIS_DEFAULTS, ANALYSIS_TYPES, SECTIONS, Analysis, Corner, Output, Setup,
                             Test, default_setup)
from ..workarea import Workarea
from . import theme

C = theme.C


class Bridge(QObject):
    """Progress from the engine's worker threads into the GUI thread."""
    progress = Signal(int, int, str)
    finished = Signal()


def _item(text, editable=True, check=None):
    it = QTableWidgetItem(str(text))
    flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
    if editable:
        flags |= Qt.ItemIsEditable
    if check is not None:
        flags |= Qt.ItemIsUserCheckable
        it.setCheckState(Qt.Checked if check else Qt.Unchecked)
    it.setFlags(flags)
    return it


def _table(headers, stretch=None):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    if stretch is not None:
        t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    return t


def _kv(text) -> dict:
    """'vdd=0.63 cload=2f' -> {'vdd': '0.63', 'cload': '2f'}"""
    out = {}
    for part in text.replace(",", " ").split():
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class OLSimWindow(QMainWindow):
    def __init__(self, setup_path, workarea: Workarea | None = None, results_dir=None, viewer=None, parent=None,
                 xschem=None, open_cell=None):
        super().__init__(parent)
        self.setup_path = Path(setup_path)
        self.workarea = workarea
        self._xschem = xschem                  # the hub's xschem (Select on Schematic); else one of our own
        self._open_cell = open_cell            # the hub opens a new testbench's OLSim; else a new window
        self._picker = None
        self.setup = Setup.load(self.setup_path) if self.setup_path.is_file() else default_setup()
        self.setup.path = str(self.setup_path)
        cell = workarea.cell_for_path(self.setup_path) if workarea else None
        self.results_dir = Path(results_dir) if results_dir else (
            workarea.run_dir(cell) / "olsim" if cell else self.setup_path.parent / f"{self.setup_path.stem}.results")
        self._viewer = viewer
        self.run = None
        self.history: History | None = None
        self._dirty = False
        self._loading = False
        self.bridge = Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.finished.connect(self._on_finished)
        self.resize(1250, 800)
        self._build()
        self.load_setup()
        self._load_histories(select_last=True)

    # ---- layout ---------------------------------------------------------------------------------
    def _build(self):
        tb = QToolBar("OLSim")
        tb.setObjectName("olsim")
        self.addToolBar(tb)

        def act(text, slot, key=None, tip=None):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        self.a_run = act("▶ Run", self.start_run, "F5", "Run all enabled tests at every corner and sweep point")
        self.a_stop = act("■ Stop", self.stop_run, None, "Stop the running simulations")
        self.a_stop.setEnabled(False)
        tb.addSeparator()
        act("Save", self.save, "Ctrl+S")
        tb.addSeparator()
        act("Plot Outputs", self.plot_outputs, None, "Plot the outputs marked Plot (all points) in the viewer")
        act("Viewer", lambda: self.viewer().show(), None, "The waveform viewer")
        tb.addSeparator()
        act("New Testbench…", self.new_testbench, None,
            "A testbench for a cell: its symbol, the VDD = {vdd} supply, a load on every output, a vector "
            "file and an OLSim setup")
        tb.addSeparator()
        tb.addWidget(QLabel(" Parallel jobs "))
        self.jobs = QSpinBox()
        self.jobs.setRange(1, 64)
        self.jobs.valueChanged.connect(self._mark)
        tb.addWidget(self.jobs)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(240)
        self.progress.setFormat("%v / %m points")
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

        # left: data view
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.itemChanged.connect(self._tree_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        dock = QDockWidget("Data View", self)
        dock.setObjectName("dataview")
        dock.setWidget(self.tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._build_setup_tab(), "Setup")
        self.tabs.addTab(self._build_results_tab(), "Results")
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(theme.mono_font())
        self.tabs.addTab(self.log, "Log")

    def _build_setup_tab(self):
        split = QSplitter(Qt.Vertical)
        # the test being edited
        self.test_box = QGroupBox("Test")
        form = QFormLayout(self.test_box)
        self.t_name = QLineEdit()
        self.t_enabled = QCheckBox("enabled")
        row = QHBoxLayout()
        row.addWidget(self.t_name)
        row.addWidget(self.t_enabled)
        form.addRow("Name", row)
        self.t_lib = QComboBox()
        self.t_cell = QComboBox()
        self.t_file = QLineEdit()
        self.t_file.setPlaceholderText("or a schematic (.sch) / netlist (.sp, .spice) file")
        browse = QPushButton("…")
        browse.setMaximumWidth(30)
        browse.clicked.connect(self._browse_design)
        drow = QHBoxLayout()
        drow.addWidget(self.t_lib)
        drow.addWidget(self.t_cell)
        drow.addWidget(self.t_file, 1)
        drow.addWidget(browse)
        form.addRow("Design", drow)
        self.analyses = _table(["on", "analysis", "parameters"], stretch=2)
        self.analyses.setMaximumHeight(130)
        arow = QHBoxLayout()
        arow.addWidget(self.analyses, 1)
        abtn = QVBoxLayout()
        self.add_analysis = QComboBox()
        self.add_analysis.addItems(["add analysis…", *ANALYSIS_TYPES])
        self.add_analysis.activated.connect(self._add_analysis)
        rm = QPushButton("Remove")
        rm.clicked.connect(lambda: self._remove_rows(self.analyses))
        abtn.addWidget(self.add_analysis)
        abtn.addWidget(rm)
        abtn.addStretch()
        arow.addLayout(abtn)
        form.addRow("Analyses", arow)
        self.vectors = QListWidget()
        self.vectors.setMaximumHeight(54)
        vrow = QHBoxLayout()
        vrow.addWidget(self.vectors, 1)
        vb = QVBoxLayout()
        addv = QPushButton("Add…")
        addv.clicked.connect(self._add_vector)
        rmv = QPushButton("Remove")
        rmv.clicked.connect(lambda: [self.vectors.takeItem(self.vectors.row(i)) for i in self.vectors.selectedItems()]
                            or self._mark())
        vb.addWidget(addv)
        vb.addWidget(rmv)
        vrow.addLayout(vb)
        form.addRow("Vector files", vrow)
        crow = QHBoxLayout()
        self.t_section = QComboBox()
        self.t_section.addItems(SECTIONS)
        self.t_temp = QLineEdit()
        self.t_temp.setMaximumWidth(80)
        self.t_saves = QLineEdit()
        self.t_saves.setPlaceholderText("all  (or: v(out) i(vdd) ...)")
        crow.addWidget(QLabel("model section"))
        crow.addWidget(self.t_section)
        crow.addWidget(QLabel("  temperature °C"))
        crow.addWidget(self.t_temp)
        crow.addWidget(QLabel("  save"))
        crow.addWidget(self.t_saves, 1)
        form.addRow("Simulation", crow)
        self.t_options = QLineEdit()
        self.t_options.setPlaceholderText(".options reltol=1e-4  (extra SPICE lines, ; separated)")
        form.addRow("Options", self.t_options)
        self.t_extracted = QLineEdit()
        self.t_extracted.setPlaceholderText("cells simulated with their PEX netlist instead of their schematic: "
                                            "cpu8/inv nand2 ...  (run PEX on their layouts first)")
        hier = QPushButton("Hierarchy…")
        hier.setToolTip("Choose, per cell of the testbench, its schematic or its extracted (PEX) view")
        hier.clicked.connect(self.edit_hierarchy)
        prow = QHBoxLayout()
        prow.addWidget(self.t_extracted, 1)
        prow.addWidget(hier)
        form.addRow("Post-layout", prow)
        for w in (self.t_name, self.t_file, self.t_temp, self.t_saves, self.t_options, self.t_extracted):
            w.textEdited.connect(self._mark)
        self.t_enabled.toggled.connect(self._mark)
        self.t_section.currentIndexChanged.connect(self._mark)
        self.t_lib.currentTextChanged.connect(self._lib_changed)
        self.t_cell.currentTextChanged.connect(self._mark)
        self.analyses.itemChanged.connect(self._mark)
        split.addWidget(self.test_box)

        # outputs
        out_box = QGroupBox("Outputs")
        ol = QVBoxLayout(out_box)
        self.outputs = _table(["test", "name", "expression", "spec", "plot"], stretch=2)
        self.outputs.itemChanged.connect(self._mark)
        ob = QHBoxLayout()
        for text, slot in (("Add Expression", lambda: self._add_output("")),
                           ("Add Signal…", self._add_signal), ("Select on Schematic…", self.select_on_schematic),
                           ("Remove", lambda: self._remove_rows(self.outputs)),
                           ("Calculator Help", self._calc_help)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            ob.addWidget(b)
        ob.addStretch()
        ol.addWidget(self.outputs)
        ol.addLayout(ob)
        split.addWidget(out_box)

        # variables and corners side by side
        bottom = QSplitter(Qt.Horizontal)
        var_box = QGroupBox("Design Variables (value, or a sweep: 1f 2f 4f / 0.6:0.05:0.8)")
        vl = QVBoxLayout(var_box)
        self.variables = _table(["name", "value"], stretch=1)
        self.variables.itemChanged.connect(self._mark)
        vbr = QHBoxLayout()
        for text, slot in (("Add", self._add_variable), ("Remove", lambda: self._remove_rows(self.variables)),
                           ("Copy from Cellview", self.copy_variables)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            vbr.addWidget(b)
        vbr.addStretch()
        vl.addWidget(self.variables)
        vl.addLayout(vbr)
        bottom.addWidget(var_box)
        cor_box = QGroupBox("Corners")
        cl = QVBoxLayout(cor_box)
        self.nominal = QCheckBox("Nominal (the test's section and temperature)")
        self.nominal.toggled.connect(self._mark)
        self.corners = _table(["on", "name", "section", "temp", "variables (vdd=0.63 cload=2f)"], stretch=4)
        self.corners.itemChanged.connect(self._mark)
        cbr = QHBoxLayout()
        for text, slot in (("Add", self._add_corner), ("Add PVT Set", self._add_pvt),
                           ("Remove", lambda: self._remove_rows(self.corners))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            cbr.addWidget(b)
        cbr.addStretch()
        cl.addWidget(self.nominal)
        cl.addWidget(self.corners)
        cl.addLayout(cbr)
        bottom.addWidget(cor_box)
        split.addWidget(bottom)
        split.setSizes([300, 220, 220])
        return split

    def _build_results_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("History"))
        self.history_box = QComboBox()
        self.history_box.setMinimumWidth(200)
        self.history_box.currentIndexChanged.connect(self._history_selected)
        row.addWidget(self.history_box)
        self.summary = QLabel("")
        row.addWidget(self.summary, 1)
        for text, slot in (("Plot Outputs", self.plot_outputs), ("Open in Viewer", self.open_history_in_viewer),
                           ("Delete History", self.delete_history)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        self.results = QTableWidget(0, 0)
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.cellDoubleClicked.connect(self._result_double)
        self.results.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self._result_menu)
        lay.addWidget(self.results)
        return w

    # ---- setup <-> widgets ----------------------------------------------------------------------
    def _mark(self, *_):
        if not self._loading:
            self._dirty = True
            self._title()

    def _title(self):
        self.setWindowTitle(f"OLSim - {self.setup_path.name}{' *' if self._dirty else ''}")

    def load_setup(self):
        self._loading = True
        s = self.setup
        self.jobs.setValue(s.jobs)
        self.nominal.setChecked(s.nominal)
        self.outputs.setRowCount(0)
        for o in s.outputs:
            self._add_output_row(o)
        self.variables.setRowCount(0)
        for k, v in s.variables.items():
            r = self.variables.rowCount()
            self.variables.insertRow(r)
            self.variables.setItem(r, 0, _item(k))
            self.variables.setItem(r, 1, _item(v))
        self.corners.setRowCount(0)
        for c in s.corners:
            self._add_corner_row(c)
        self._current_test = s.tests[0].name if s.tests else None
        self._show_test()
        self._refresh_tree()
        self._loading = False
        self._dirty = False
        self._title()

    def _show_test(self):
        t = self.setup.test(self._current_test) if self._current_test else None
        self.test_box.setEnabled(t is not None)
        if t is None:
            return
        was = self._loading
        self._loading = True
        self.t_name.setText(t.name)
        self.t_enabled.setChecked(t.enabled)
        self.t_lib.clear()
        self.t_cell.clear()
        libs = [lb.name for lb in self.workarea.libraries()] if self.workarea else []
        self.t_lib.addItems([""] + libs)
        self.t_lib.setVisible(bool(libs))
        self.t_cell.setVisible(bool(libs))
        if "lib" in t.design:
            self.t_lib.setCurrentText(t.design["lib"])
            self._lib_changed(t.design["lib"])
            self.t_cell.setCurrentText(t.design["cell"])
            self.t_file.setText("")
        else:
            self.t_file.setText(t.design.get("schematic") or t.design.get("netlist") or "")
        self.analyses.setRowCount(0)
        for a in t.analyses:
            self._add_analysis_row(a)
        self.vectors.clear()
        self.vectors.addItems(t.vectors)
        self.t_section.setCurrentText(t.section)
        self.t_temp.setText(t.temp)
        self.t_saves.setText(t.saves)
        self.t_options.setText(t.options.replace("\n", " ; "))
        self.t_extracted.setText(" ".join(t.extracted))
        self._loading = was

    def _lib_changed(self, lib):
        if not self._loading:
            self._mark()
        self.t_cell.clear()
        if self.workarea and lib and self.workarea.library(lib):
            cells = [c.name for c in self.workarea.library(lib).cells() if c.view("schematic")]
            self.t_cell.addItems(cells)

    def _read_test(self):
        """Widgets -> the current test."""
        t = self.setup.test(self._current_test) if self._current_test else None
        if t is None:
            return
        new_name = self.t_name.text().strip() or t.name
        if new_name != t.name:
            for o in self.setup.outputs:
                if o.test == t.name:
                    o.test = new_name
            t.name = self._current_test = new_name
        t.enabled = self.t_enabled.isChecked()
        f = self.t_file.text().strip()
        if f:
            t.design = {"netlist": f} if not f.endswith(".sch") else {"schematic": f}
        elif self.t_lib.currentText() and self.t_cell.currentText():
            t.design = {"lib": self.t_lib.currentText(), "cell": self.t_cell.currentText()}
        t.analyses = []
        for r in range(self.analyses.rowCount()):
            typ = self.analyses.item(r, 1).text()
            params = _kv(self.analyses.item(r, 2).text())
            t.analyses.append(Analysis(typ, self.analyses.item(r, 0).checkState() == Qt.Checked, params))
        t.vectors = [self.vectors.item(i).text() for i in range(self.vectors.count())]
        t.section = self.t_section.currentText()
        t.temp = self.t_temp.text().strip() or "27"
        t.saves = self.t_saves.text().strip() or "all"
        t.options = "\n".join(p.strip() for p in self.t_options.text().split(";") if p.strip())
        t.extracted = self.t_extracted.text().replace(",", " ").split()

    def read_setup(self) -> Setup:
        """Widgets -> self.setup."""
        self._read_test()
        s = self.setup
        s.jobs = self.jobs.value()
        s.nominal = self.nominal.isChecked()
        s.outputs = []
        for r in range(self.outputs.rowCount()):
            g = lambda c: (self.outputs.item(r, c).text() if self.outputs.item(r, c) else "").strip()  # noqa: E731
            if not g(1) or not g(2):
                continue
            s.outputs.append(Output(g(0), g(1), g(2), g(3), self.outputs.item(r, 4).checkState() == Qt.Checked))
        s.variables = {}
        for r in range(self.variables.rowCount()):
            k = self.variables.item(r, 0).text().strip() if self.variables.item(r, 0) else ""
            if k:
                s.variables[k] = self.variables.item(r, 1).text().strip() if self.variables.item(r, 1) else ""
        s.corners = []
        for r in range(self.corners.rowCount()):
            g = lambda c: (self.corners.item(r, c).text() if self.corners.item(r, c) else "").strip()  # noqa: E731
            if not g(1):
                continue
            s.corners.append(Corner(g(1), self.corners.item(r, 0).checkState() == Qt.Checked, g(2), g(3), _kv(g(4))))
        return s

    def save(self):
        self.read_setup().save(self.setup_path)
        self._dirty = False
        self._title()
        self._refresh_tree()
        self.statusBar().showMessage(f"saved {self.setup_path}", 4000)

    # ---- rows -----------------------------------------------------------------------------------
    def _add_analysis_row(self, a):
        r = self.analyses.rowCount()
        self.analyses.insertRow(r)
        self.analyses.setItem(r, 0, _item("", False, a.enabled))
        self.analyses.setItem(r, 1, _item(a.type, False))
        p = {**ANALYSIS_DEFAULTS[a.type], **a.params}
        self.analyses.setItem(r, 2, _item(" ".join(f"{k}={v}" for k, v in p.items())))

    def _add_analysis(self, idx):
        if idx <= 0:
            return
        self._add_analysis_row(Analysis(self.add_analysis.itemText(idx)))
        self.add_analysis.setCurrentIndex(0)
        self._mark()

    def _add_output_row(self, o):
        r = self.outputs.rowCount()
        self.outputs.insertRow(r)
        for c, v in enumerate((o.test, o.name, o.expr, o.spec)):
            self.outputs.setItem(r, c, _item(v))
        self.outputs.setItem(r, 4, _item("", False, o.plot))

    def _add_output(self, expr, name=None, plot=False):
        n = name or f"out{self.outputs.rowCount() + 1}"
        self._add_output_row(Output(self._current_test or "", n, expr, "", plot))
        self._mark()

    def _add_signal(self):
        """Signals of the last run's raw file, or the testbench nets (v(...) outputs to plot)."""
        names = []
        if self.history and self.history.points:
            for p in self.history.plots(self.history.points[0]["index"]):
                names += [n for n in p.signals() if n not in names]
        if not names:
            QMessageBox.information(self, "Add Signal", "Run once first; then the simulated signals can be "
                                    "picked from the list. Meanwhile, add an expression like v(\"out\").")
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getItem(self, "Add Signal", "Signal to plot", names, 0, False)
        if ok and name:
            self._add_output(f'v("{name[2:-1]}")' if name.startswith("v(") else f'i("{name[2:-1]}")'
                             if name.startswith("i(") else f'v("{name}")', name.replace("(", "_").rstrip(")"), True)

    def _add_variable(self):
        r = self.variables.rowCount()
        self.variables.insertRow(r)
        self.variables.setItem(r, 0, _item(f"var{r + 1}"))
        self.variables.setItem(r, 1, _item("0"))
        self._mark()

    def _add_corner_row(self, c):
        r = self.corners.rowCount()
        self.corners.insertRow(r)
        self.corners.setItem(r, 0, _item("", False, c.enabled))
        self.corners.setItem(r, 1, _item(c.name))
        self.corners.setItem(r, 2, _item(c.section))
        self.corners.setItem(r, 3, _item(c.temp))
        self.corners.setItem(r, 4, _item(" ".join(f"{k}={v}" for k, v in c.variables.items())))

    def _add_corner(self):
        self._add_corner_row(Corner(f"C{self.corners.rowCount() + 1}", True, "ss", "125"))
        self._mark()

    def _add_pvt(self):
        """The usual signoff set: ss/125 C/-10 % supply, ff/-40 C/+10 % supply (vdd from the variables)."""
        vdd = None
        for r in range(self.variables.rowCount()):
            if self.variables.item(r, 0) and self.variables.item(r, 0).text().strip().lower() == "vdd":
                try:
                    vdd = si(self.variables.item(r, 1).text())
                except ValueError:
                    pass
        for name, sec, temp, k in (("ss_hot", "ss", "125", 0.9), ("ff_cold", "ff", "-40", 1.1),
                                   ("tt_hot", "tt", "125", 1.0), ("ss_cold", "ss", "-40", 0.9)):
            vars_ = {"vdd": fmt(vdd * k)} if vdd else {}
            self._add_corner_row(Corner(name, True, sec, temp, vars_))
        self._mark()

    def _remove_rows(self, table):
        for r in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(r)
        self._mark()

    def _browse_design(self):
        f, _ = QFileDialog.getOpenFileName(self, "Testbench", str(self.setup_path.parent),
                                           "Schematics and netlists (*.sch *.sp *.spice *.cir);;All files (*)")
        if f:
            self.t_file.setText(f)
            self._mark()

    def _add_vector(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Vector files", str(self.setup_path.parent),
                                                "Vector files (*.vec);;All files (*)")
        for f in files:
            try:
                f = str(Path(f).relative_to(self.setup_path.parent))
            except ValueError:
                pass
            self.vectors.addItem(f)
        if files:
            self._mark()

    def copy_variables(self):
        """Variables > Copy from Cellview: the {names} the testbench uses."""
        self._read_test()
        t = self.setup.test(self._current_test)
        try:
            r = Run(self.read_setup(), self.results_dir, self.workarea.root if self.workarea else None, name=".netlist")
            r.path.mkdir(parents=True, exist_ok=True)
            body, _, _ = r._netlist(t)
        except Exception as e:
            QMessageBox.warning(self, "Copy from Cellview", f"Could not netlist the testbench:\n{e}")
            return
        have = {self.variables.item(r, 0).text() for r in range(self.variables.rowCount()) if self.variables.item(r, 0)}
        added = [v for v in design_variables(body) if v not in have]
        for v in added:
            r = self.variables.rowCount()
            self.variables.insertRow(r)
            self.variables.setItem(r, 0, _item(v))
            self.variables.setItem(r, 1, _item(""))
        self.statusBar().showMessage(f"{len(added)} variable(s) from the testbench: {', '.join(added) or 'none new'}"
                                     " - give them values", 8000)
        if added:
            self._mark()

    def _calc_help(self):
        from ..olsim import calc
        QMessageBox.information(self, "Calculator", calc.__doc__)

    # ---- data view ------------------------------------------------------------------------------
    def _refresh_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        tests = QTreeWidgetItem(self.tree, ["Tests"])
        for t in self.setup.tests:
            it = QTreeWidgetItem(tests, [t.name])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if t.enabled else Qt.Unchecked)
            it.setData(0, Qt.UserRole, ("test", t.name))
            QTreeWidgetItem(it, [f"design: {t.design_label()}"])
            for a in t.analyses:
                QTreeWidgetItem(it, [("" if a.enabled else "(off) ") + a.summary()])
            for v in t.vectors:
                QTreeWidgetItem(it, [f"vectors: {v}"])
            for x in t.extracted:
                QTreeWidgetItem(it, [f"extracted: {x}"])
            QTreeWidgetItem(it, [f"{t.section}, {t.temp} °C"])
            if t.name == self._current_test:
                self.tree.setCurrentItem(it)
        tests.setExpanded(True)
        for it in (tests.child(i) for i in range(tests.childCount())):
            it.setExpanded(True)
        v = QTreeWidgetItem(self.tree, [f"Global Variables ({len(self.setup.variables)})"])
        for k, val in self.setup.variables.items():
            QTreeWidgetItem(v, [f"{k} = {val}"])
        v.setExpanded(True)
        c = QTreeWidgetItem(self.tree, [f"Corners ({sum(1 for x in self.setup.corners if x.enabled)} on)"])
        for x in self.setup.corners:
            QTreeWidgetItem(c, [("" if x.enabled else "(off) ") + x.name])
        c.setExpanded(True)
        n = len(self.setup.points())
        QTreeWidgetItem(self.tree, [f"{n} point(s) to run"])
        self.tree.blockSignals(False)

    def _tree_clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "test" and data[1] != self._current_test:
            self._read_test()
            self._current_test = data[1]
            self._show_test()
            self.tabs.setCurrentIndex(0)

    def _tree_changed(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "test":
            t = self.setup.test(data[1])
            t.enabled = item.checkState(0) == Qt.Checked
            if t.name == self._current_test:
                self.t_enabled.setChecked(t.enabled)
            self._mark()

    def _tree_menu(self, pos):
        m = QMenu(self)
        m.addAction("New Test", self.new_test)
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item else None
        if data and data[0] == "test":
            m.addAction(f"Copy Test {data[1]}", lambda: self.copy_test(data[1]))
            m.addAction(f"Delete Test {data[1]}", lambda: self.delete_test(data[1]))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def new_test(self):
        self._read_test()
        base = self.setup.tests[0].design if self.setup.tests else {}
        name = f"test{len(self.setup.tests) + 1}"
        self.setup.tests.append(Test(name, dict(base), [Analysis("tran", True, {"step": "1p", "stop": "1n"})]))
        self._current_test = name
        self._show_test()
        self._refresh_tree()
        self._mark()

    def copy_test(self, name):
        self._read_test()
        t = self.setup.test(name)
        copy = Test(f"{name}_copy", dict(t.design), [Analysis(a.type, a.enabled, dict(a.params)) for a in t.analyses],
                    list(t.vectors), t.enabled, t.section, t.temp, t.options, t.saves, dict(t.variables),
                    list(t.extracted))
        self.setup.tests.append(copy)
        self.setup.outputs += [Output(copy.name, o.name, o.expr, o.spec, o.plot, o.analysis)
                               for o in self.setup.outputs if o.test == name]
        for o in self.setup.outputs[-sum(1 for o in self.setup.outputs if o.test == copy.name):]:
            self._add_output_row(o)
        self._current_test = copy.name
        self._show_test()
        self._refresh_tree()
        self._mark()

    def delete_test(self, name):
        if len(self.setup.tests) == 1:
            return
        self.setup.tests = [t for t in self.setup.tests if t.name != name]
        self.setup.outputs = [o for o in self.setup.outputs if o.test != name]
        self._current_test = self.setup.tests[0].name
        self.load_setup()
        self._mark()

    # ---- running --------------------------------------------------------------------------------
    def start_run(self):
        if self.run and self.run.running():
            return
        setup = self.read_setup()
        try:
            setup.save(self.setup_path)                # OLSim saves the setup with each run
            self._dirty = False
            self._title()
            n = len(setup.points())
        except Exception as e:
            QMessageBox.warning(self, "Run", str(e))
            return
        self._refresh_tree()
        self.log.appendPlainText(f"---- run: {n} point(s), {setup.jobs} in parallel")
        self.run = Run(Setup.load(self.setup_path), self.results_dir, self.workarea.root if self.workarea else None)
        self.progress.setRange(0, n)
        self.progress.setValue(0)
        self.progress.show()
        self.a_run.setEnabled(False)
        self.a_stop.setEnabled(True)
        self.run.start(lambda d, t, m: self.bridge.progress.emit(d, t, m))

        def wait():
            self.run._thread.join()
            self.bridge.finished.emit()
        threading.Thread(target=wait, daemon=True).start()

    def stop_run(self):
        if self.run:
            self.run.cancel()
            self.log.appendPlainText("---- stopping")

    def _on_progress(self, done, total, msg):
        self.progress.setValue(done)
        self.log.appendPlainText(msg)
        self.statusBar().showMessage(msg, 5000)

    def _on_finished(self):
        self.progress.hide()
        self.a_run.setEnabled(True)
        self.a_stop.setEnabled(False)
        if self.run.error:
            self.log.appendPlainText(f"ERROR: {self.run.error}")
            QMessageBox.warning(self, "OLSim", self.run.error)
            return
        self.log.appendPlainText(f"---- {self.run.name}: {self.run.history.data['status']}")
        self._load_histories(select=self.run.name)
        self.tabs.setCurrentIndex(1)
        if any(o.plot for o in self.setup.outputs):
            self.plot_outputs()

    # ---- results --------------------------------------------------------------------------------
    def _load_histories(self, select=None, select_last=False):
        self.history_box.blockSignals(True)
        self.history_box.clear()
        hs = histories(self.results_dir)
        for h in hs:
            self.history_box.addItem(h.name, str(h))
        self.history_box.blockSignals(False)
        if not hs:
            self.history = None
            self.results.setRowCount(0)
            self.results.setColumnCount(0)
            self.summary.setText("no results yet - Run (F5)")
            return
        idx = self.history_box.findText(select) if select else (len(hs) - 1 if select_last else 0)
        self.history_box.setCurrentIndex(max(0, idx))
        self._history_selected()

    def _history_selected(self, *_):
        path = self.history_box.currentData()
        if not path:
            return
        try:
            self.history = History.load(path)
        except Exception as e:
            self.summary.setText(f"cannot read {path}: {e}")
            return
        self.show_results()

    def show_results(self):
        h = self.history
        pts = h.points
        names = [o["name"] for o in h.outputs]
        if any("vector errors" in h.result(p["index"]) for p in pts):
            names.append("vector errors")
        self.results.clear()
        self.results.setColumnCount(len(pts) + 3)
        self.results.setRowCount(len(names) + 1)
        self.results.setHorizontalHeaderLabels(["output", "spec", "min / max"] +
                                               [f"{p['index']}: {p['test']}\n{p['label']}" for p in pts])
        self.results.setVerticalHeaderLabels([""] * (len(names) + 1))
        self.results.setItem(0, 0, QTableWidgetItem("status"))
        passed = failed = errs = 0
        for c, p in enumerate(pts):
            st = h.result(p["index"]).get("_status", "")
            it = QTableWidgetItem(st or "-")
            if st != "done":
                it.setForeground(QBrush(QColor(C["fail"] if st else C["dim"])))
                errs += bool(st)
            self.results.setItem(0, c + 3, it)
        specs = {o["name"]: o.get("spec", "") for o in h.outputs}
        specs["vector errors"] = "== 0"
        for r, name in enumerate(names, start=1):
            self.results.setItem(r, 0, QTableWidgetItem(name))
            self.results.setItem(r, 1, QTableWidgetItem(specs.get(name, "")))
            nums = []
            for c, p in enumerate(pts):
                e = h.result(p["index"]).get(name)
                it = QTableWidgetItem("")
                if e is None:
                    pass
                elif e.get("error"):
                    it.setText("error")
                    it.setToolTip(e["error"])
                    it.setForeground(QBrush(QColor(C["warn"])))
                else:
                    v = e.get("value")
                    if isinstance(v, dict) and "wave" in v:
                        it.setText("〰 wave")
                        it.setForeground(QBrush(QColor(C["accent"])))
                        it.setToolTip("double-click to plot")
                    else:
                        if isinstance(v, dict):
                            v = complex(v["re"], v["im"])
                        it.setText(fmt(v))
                        if isinstance(v, (int, float)):
                            nums.append(v)
                        if e.get("first"):
                            it.setToolTip("\n".join(e["first"]))
                    ok = e.get("pass")
                    if ok is True:
                        it.setBackground(QBrush(QColor("#1f3d2c")))
                        passed += 1
                    elif ok is False:
                        it.setBackground(QBrush(QColor("#4a2326")))
                        failed += 1
                self.results.setItem(r, c + 3, it)
            if nums:
                self.results.setItem(r, 2, QTableWidgetItem(f"{fmt(min(nums))} / {fmt(max(nums))}"))
        self.results.resizeColumnsToContents()
        self.results.horizontalHeader().setStretchLastSection(False)
        status = h.data.get("status", "")
        self.summary.setText(f"  {len(pts)} point(s), {status}:  {passed} pass, {failed} fail"
                             + (f", {errs} simulation error(s)" if errs else ""))

    def _result_name(self, row):
        it = self.results.item(row, 0)
        return it.text() if it and row > 0 else None

    def _result_double(self, row, col):
        name = self._result_name(row)
        if not name or not self.history:
            return
        if col >= 3:
            p = self.history.points[col - 3]
            if row == 0:
                self._show_files(p["index"])
                return
            if name == "vector errors":
                self.plot_vectors(p["index"])
                return
            if not self._is_wave(name):
                return
            self.viewer().plot_output(self.history, name, [p["index"]])
        elif self._is_wave(name):
            self.viewer().plot_output(self.history, name)
        else:
            swept = self._swept()
            if swept:
                self.plot_vs(name, swept[0])
            return
        self.viewer().show()
        self.viewer().raise_()

    def _is_wave(self, name):
        return any(isinstance(self.history.result(p["index"]).get(name, {}).get("value"), dict)
                   and "wave" in self.history.result(p["index"])[name]["value"] for p in self.history.points)

    def _swept(self):
        names = []
        for p in self.history.points:
            for k in p.get("swept", []):
                if k not in names:
                    names.append(k)
        return names

    def plot_vs(self, name, var):
        """A scalar output against a swept variable, one curve per corner (and per value of the
        other swept variables) - OLSim's "plot across design points"."""
        groups = {}
        for p in self.history.points:
            e = self.history.result(p["index"]).get(name) or {}
            v = e.get("value")
            if e.get("error") or not isinstance(v, (int, float)):
                continue
            try:
                x = si(p["variables"][var])
            except (KeyError, ValueError):
                continue
            others = ", ".join(f"{k}={p['variables'][k]}" for k in p.get("swept", []) if k != var)
            key = f"{p['test']} {p['corner']}" + (f" {others}" if others else "")
            groups.setdefault(key, []).append((x, v))
        v = self.viewer()
        expr = next((o["expr"] for o in self.history.outputs if o["name"] == name), "")
        first = True
        for key, pts in groups.items():
            xs, ys = zip(*sorted(pts))
            v.plot_xy(xs, ys, f"{name} {key}", var, variable_unit(var), guess_unit(expr), new_strip=first)
            first = False
        v.show()
        v.raise_()

    def plot_vectors(self, index):
        try:
            self.viewer().plot_vector_check(self.history, index)
        except Exception as e:
            QMessageBox.information(self, "Vectors", str(e))
            return
        self.viewer().show()
        self.viewer().raise_()

    def _result_menu(self, pos):
        idx = self.results.indexAt(pos)
        name = self._result_name(idx.row())
        if not self.history:
            return
        m = QMenu(self)
        if name and name != "vector errors" and self._is_wave(name):
            m.addAction(f"Plot {name} Across All Points", lambda: (self.viewer().plot_output(self.history, name),
                                                                   self.viewer().show()))
        elif name and name != "vector errors":
            for var in self._swept():
                m.addAction(f"Plot {name} vs {var}", lambda var=var: self.plot_vs(name, var))
        if idx.column() >= 3:
            p = self.history.points[idx.column() - 3]
            if name == "vector errors" or "vector errors" in self.history.result(p["index"]):
                m.addAction(f"Plot Vector Check of Point {p['index']}", lambda: self.plot_vectors(p["index"]))
            m.addAction(f"Open Point {p['index']} in Viewer", lambda: self._open_point(p["index"]))
            m.addAction(f"Show Deck and Log of Point {p['index']}", lambda: self._show_files(p["index"]))
        m.exec(self.results.viewport().mapToGlobal(pos))

    def _show_files(self, index):
        d = self.history.path / "points" / str(index)
        text = []
        for f in ("deck.sp", "vector_errors.json", "ngspice.log"):
            if (d / f).is_file():
                body = (d / f).read_text(errors="replace")
                text.append(f"==== {f}\n" + (body[-6000:] if f == "ngspice.log" else body[:20000]))
        self.log.setPlainText("\n".join(text))
        self.tabs.setCurrentIndex(2)

    def _open_point(self, index):
        v = self.viewer()
        v.add_history(self.history)
        v.show()
        v.raise_()

    def plot_outputs(self):
        if not self.history:
            return
        v = self.viewer()
        for o in self.history.outputs:
            if o.get("plot"):
                v.plot_output(self.history, o["name"])
        v.show()
        v.raise_()

    def open_history_in_viewer(self):
        if self.history:
            self._open_point(0)

    def delete_history(self):
        if not self.history:
            return
        if QMessageBox.question(self, "Delete History", f"Delete {self.history.name} and its files?") \
                != QMessageBox.Yes:
            return
        delete_history(self.history.path)
        self._load_histories(select_last=True)

    # ---- hierarchy, schematic picking, testbenches ----------------------------------------------
    def _netlist_run(self):
        r = Run(self.read_setup(), self.results_dir, self.workarea.root if self.workarea else None, name=".netlist")
        r.path.mkdir(parents=True, exist_ok=True)
        return r

    def edit_hierarchy(self):
        """Per cell of the testbench: schematic or extracted view (the test's Post-layout list)."""
        from .olsim_dialogs import HierarchyDialog
        self._read_test()
        t = self.setup.test(self._current_test)
        try:
            dlg = HierarchyDialog(self, self._netlist_run(), t, self.workarea)
        except Exception as e:
            QMessageBox.warning(self, "Hierarchy", f"Could not netlist the testbench:\n{e}")
            return None
        if dlg.exec():
            self.t_extracted.setText(" ".join(dlg.extracted()))
            self._mark()
            self._read_test()
            self._refresh_tree()
        return dlg

    def xschem(self):
        if self._xschem is None and self.workarea is not None:
            from ..tools import XschemBridge
            self._xschem = XschemBridge(self.workarea)
        return self._xschem

    def select_on_schematic(self):
        """Open the test's testbench in xschem; what is selected there becomes plotted outputs."""
        from .olsim_dialogs import SchematicPicker
        self._read_test()
        t = self.setup.test(self._current_test)
        bridge = self.xschem()
        if bridge is None:
            QMessageBox.information(self, "Select on Schematic", "Selecting on the schematic needs a workarea "
                                    "(xschem runs in it).")
            return None
        view = path = None
        if "lib" in t.design:
            lib = self.workarea.library(t.design["lib"])
            cell = lib.cell(t.design["cell"]) if lib else None
            view = cell.view("schematic") if cell else None
        elif "schematic" in t.design:
            path = self._netlist_run()._resolve(t.design["schematic"])
        if view is None and path is None:
            QMessageBox.information(self, "Select on Schematic", "This test simulates a netlist, not a schematic.")
            return None
        have = {self.outputs.item(r, 2).text() for r in range(self.outputs.rowCount()) if self.outputs.item(r, 2)}
        if self._picker is not None:
            self._picker.close()
        self._picker = SchematicPicker(self, bridge, lambda expr, name: self._add_output(expr, name, plot=True), have)
        try:
            self._picker.start(view, path)
        except Exception as e:
            QMessageBox.warning(self, "Select on Schematic", f"Could not open the schematic in xschem:\n{e}")
            return None
        return self._picker

    def new_testbench(self, dut=None):
        """tb_<cell> for a cell (default: the current test's design, if it is a circuit with pins)."""
        from ..olsim.testbench import is_testbench, make_testbench
        if self.workarea is None:
            QMessageBox.information(self, "New Testbench", "Testbenches are made in a workarea.")
            return None
        if dut is None:
            self._read_test()
            t = self.setup.test(self._current_test)
            choices = [f"{lb.name}/{c.name}" for lb in self.workarea.libraries() if not lb.readonly
                       for c in lb.cells() if c.view("schematic") and not is_testbench(c)]
            if not choices:
                QMessageBox.information(self, "New Testbench", "No circuit with pins in the writable libraries.")
                return None
            cur = f"{t.design.get('lib')}/{t.design.get('cell')}" if t and "lib" in t.design else ""
            from PySide6.QtWidgets import QInputDialog
            dut, ok = QInputDialog.getItem(self, "New Testbench", "Cell to test", choices,
                                           choices.index(cur) if cur in choices else 0, False)
            if not ok:
                return None
        lib_name, cell_name = dut.split("/")
        try:
            tb = make_testbench(self.workarea, self.workarea.library(lib_name), cell_name)
        except Exception as e:
            QMessageBox.warning(self, "New Testbench", str(e))
            return None
        self.statusBar().showMessage(f"created {tb.key}: supply VDD = {{vdd}}, loads {{cload}}, vectors in "
                                     f"{tb.name}.vec (fill in the expected outputs)", 10000)
        if self._open_cell:
            self._open_cell(tb)
        else:
            w = OLSimWindow(tb.path / f"{tb.name}.olsim", self.workarea, viewer=self._viewer)
            w.show()
            self._children = getattr(self, "_children", []) + [w]
        return tb

    def viewer(self):
        if self._viewer is None:
            from .waveview import Viewer
            self._viewer = Viewer()
        return self._viewer

    def closeEvent(self, e):
        if self._dirty:
            r = QMessageBox.question(self, "OLSim", "Save the setup changes?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                e.ignore()
                return
            if r == QMessageBox.Save:
                self.save()
        if self.run and self.run.running():
            self.run.cancel()
        super().closeEvent(e)


def main(argv=None):
    from ..olsim.cli import locate
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme.apply(app)
    wa = Workarea.find(".")
    if argv:
        f, results = locate(argv, wa)
    else:
        f, _ = QFileDialog.getOpenFileName(None, "OLSim setup", ".", "OLSim (*.olsim)")
        if not f:
            return 0
        f, results = locate([f], wa)
    w = OLSimWindow(f, wa, results)
    w.show()
    return app.exec()
