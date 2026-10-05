"""The waveform viewer: results of OLSim runs and SPICE raw files, plotted
in stacked strips with linked time axes, overlays across corners and sweeps, A / B cursors with a
readout, markers, a calculator, log / dB / phase display and PNG / CSV export. Plotting is
pyqtgraph (MIT): fast enough for millions of points, zoom and pan with the mouse.

    openlayout waves [file.raw ... | <olsim history dir>]

Mouse: wheel zooms, left drag pans (zoom box mode: drags a box), right drag zooms an axis,
double-click a signal in the browser to plot it. Keys: F fit, A / B put the cursor at the mouse,
M marker at the nearest point, Delete removes the selected curve, Ctrl+N new strip.
"""
from __future__ import annotations

import csv
import fnmatch
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
import numpy as np  # noqa: E402
from PySide6.QtCore import Qt, Signal  # noqa: E402
from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog,  # noqa: E402
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow,
                               QMenu, QPushButton, QTableWidget, QTableWidgetItem, QToolBar,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
import pyqtgraph as pg  # noqa: E402
import pyqtgraph.exporters  # noqa: E402,F401

from ..olsim import rawfile  # noqa: E402
from ..olsim.calc import CalcError, Context, Waveform, evaluate, fmt  # noqa: E402
from . import theme  # noqa: E402

CANVAS = theme.THEME["canvas"]
COLORS = ["#4fa3ff", "#ef6b6b", "#4cc38a", "#e8b04b", "#c678dd", "#4dd0c4", "#ff8a80", "#bfff81",
          "#d16ba5", "#d2d46b", "#5fb4ff", "#fdb200", "#9fb7a5", "#ef6158", "#7bd88f", "#b5a642"]
UNITS = {"time": "s", "frequency": "Hz", "voltage": "V", "current": "A", "v-sweep": "V", "i-sweep": "A",
         "temp-sweep": "°C"}

pg.setConfigOptions(antialias=True, background=CANVAS["background"], foreground=CANVAS["text"])


def _unit_of(name, unit_word):
    n = name.lower()
    if n.startswith("i(") or n.endswith("#branch"):
        return "A"
    if n.startswith("v(") or unit_word == "voltage":
        return "V"
    return UNITS.get(unit_word, "")


# ---- data sources -------------------------------------------------------------------------------
class Source:
    """Something with plots to browse: a raw file, or one point of a OLSim history."""

    def __init__(self, label, loader, variables=None, history=None, index=None):
        self.label = label
        self._loader = loader
        self._plots = None
        self.variables = variables or {}
        self.history = history
        self.index = index

    @property
    def plots(self):
        if self._plots is None:
            self._plots = self._loader()
        return self._plots

    def wave(self, kind, name):
        p = next(pl for pl in self.plots if pl.kind == kind)
        return Waveform(p.x, p[name], name, p.scale), p

    def context(self, kind=None):
        return Context(self.plots, self.variables, kind)


# ---- one curve on a strip -----------------------------------------------------------------------
class Curve:
    def __init__(self, item, x, y, label, unit, xunit):
        self.item, self.x, self.y = item, x, y
        self.label, self.unit, self.xunit = label, unit, xunit
        self.lane = None                  # digital lanes: the lane's base (y), values 0 / 1 above it
        self.bus = None                   # bus lanes: [(t0, t1, value text)]
        self.key = None                   # (source index, analysis, signal) when plotted from the browser
        self.strip = None
        self.in_legend = True
        self.visible = True

    def text_at(self, x):
        """The readout text at x: a number, a logic level, or a bus value."""
        if x is None:
            return ""
        if self.bus is not None:
            return next((v for t0, t1, v in self.bus if t0 <= x < t1), "")
        y = self.at(x)
        if y is None or y != y:
            return ""
        if self.lane is not None:
            return "1" if y - self.lane > 0.5 else "0"
        return f"{fmt(y)}{self.unit}"

    def at(self, x):
        if len(self.x) == 0 or x is None:
            return None
        if self.x[0] > self.x[-1]:
            return float(np.interp(x, self.x[::-1], self.y[::-1]))
        return float(np.interp(x, self.x, self.y))


class Strip:
    """One plot of the stack."""

    def __init__(self, viewer, plot: pg.PlotItem):
        self.viewer, self.plot = viewer, plot
        self.curves: list[Curve] = []
        self.xunit = None
        self.xkind = None
        self.legend = plot.addLegend(offset=(-10, 10), labelTextColor=CANVAS["text"])
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setClipToView(True)
        # (no automatic downsampling: pyqtgraph sizes it from the initial 0..1 view and loses
        # sub-nanosecond data - long curves get a fixed peak-preserving factor in add())
        plot.getAxis("left").setWidth(64)
        self.cursors = {}
        self.hcursor = None

    def add(self, x, y, label, unit, xunit, xkind, color=None, style=Qt.SolidLine, symbol=None, legend=True):
        color = color or COLORS[self.viewer.next_color() % len(COLORS)]
        pen = pg.mkPen(color=color, width=1.6, style=style)
        item = self.plot.plot(x, y, pen=pen, name=label if legend else None, connect="finite")
        if symbol:
            item.setSymbol(symbol)
            item.setSymbolSize(7)
            item.setSymbolBrush(pg.mkBrush(color))
            item.setSymbolPen(None)
        if len(x) > 200_000:
            item.setDownsampling(ds=len(x) // 100_000, auto=False, method="peak")
        item.curve.setClickable(True, width=6)
        item.sigClicked.connect(lambda *_: self.viewer.select_curve(self, item))
        c = Curve(item, np.asarray(x, float), np.asarray(y, float), label, unit, xunit)
        c.strip, c.in_legend = self, legend
        self.curves.append(c)
        if self.xunit is None:
            self.xunit, self.xkind = xunit, xkind
            self.plot.setLabel("bottom", units=xunit)
        units = {cv.unit for cv in self.curves}
        self.plot.setLabel("left", units=units.pop() if len(units) == 1 else "")
        return c

    def set_visible(self, curve, on):
        """Show / hide a curve (hidden: off the plot and the legend, kept for showing again)."""
        if curve.visible == on:
            return
        curve.visible = on
        curve.item.setVisible(on)
        if curve.in_legend:
            if on:
                self.legend.addItem(curve.item, curve.label)
            else:
                self.legend.removeItem(curve.item)

    def remove(self, curve):
        self.plot.removeItem(curve.item)
        self.legend.removeItem(curve.item)
        self.curves.remove(curve)
        self.viewer.forget(curve)

    def clear(self):
        for c in list(self.curves):
            self.remove(c)
        self.xunit = self.xkind = None


# ---- the viewer ---------------------------------------------------------------------------------
class Viewer(QMainWindow):
    cursorsMoved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenLayout Waveform Viewer")
        self.resize(1300, 820)
        self.sources: list[Source] = []
        self.strips: list[Strip] = []
        self.active = None
        self.selected = None             # (strip, curve)
        self._color = 0
        self.cursor_x = {"A": None, "B": None}
        self.markers = []
        self.keyed = {}                  # (source index, analysis, signal) -> [Curve] plotted from it
        self._readout_curves = []
        self.layout_widget = pg.GraphicsLayoutWidget()
        self.layout_widget.ci.setSpacing(4)
        self.setCentralWidget(self.layout_widget)
        self._build_browser()
        self._build_readout()
        self._build_calculator()
        self._build_toolbar()
        self.layout_widget.scene().sigMouseMoved.connect(self._mouse_moved)
        self.layout_widget.scene().sigMouseClicked.connect(self._scene_clicked)
        self._mouse = None
        self.new_strip()
        self.statusBar().showMessage("Double-click a signal (or tick it) to plot it, untick to hide it; "
                                     "A / B place the cursors, F fits")

    # ---- UI -------------------------------------------------------------------------------------
    def _build_browser(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        self.filter = QLineEdit(placeholderText="Filter signals (out*, i(*))")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.internal = QCheckBox("Internal device nodes")
        self.internal.toggled.connect(self.refresh_browser)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self._tree_double)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemChanged.connect(self._tree_checked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        lay.addWidget(self.filter)
        lay.addWidget(self.tree)
        lay.addWidget(self.internal)
        dock = QDockWidget("Results", self)
        dock.setObjectName("results")
        dock.setWidget(w)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_readout(self):
        self.readout = QTableWidget(0, 5)
        self.readout.setHorizontalHeaderLabels(["curve (visible)", "A", "B", "B - A", ""])
        self.readout.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.readout.verticalHeader().setVisible(False)
        self.readout.setEditTriggers(QTableWidget.NoEditTriggers)
        self.readout.itemChanged.connect(self._readout_checked)
        self.cursor_label = QLabel("cursors: press A / B over a strip")
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addWidget(self.cursor_label)
        lay.addWidget(self.readout)
        dock = QDockWidget("Cursors", self)
        dock.setObjectName("cursors")
        dock.setWidget(w)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def _build_calculator(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 2)
        row = QHBoxLayout()
        self.calc_source = QComboBox()
        self.calc_source.setMinimumWidth(220)
        self.calc_expr = QLineEdit(placeholderText='e.g.  delay(v("in"), v("out"), 0.35, 0.35, "rise", "fall")   '
                                                   'or  db20(v("out")/v("in"))')
        self.calc_expr.returnPressed.connect(self.calculate)
        go = QPushButton("Evaluate")
        go.clicked.connect(self.calculate)
        row.addWidget(QLabel("on"))
        row.addWidget(self.calc_source)
        row.addWidget(self.calc_expr, 1)
        row.addWidget(go)
        self.calc_log = QListWidget()
        self.calc_log.setFont(theme.mono_font())
        lay.addLayout(row)
        lay.addWidget(self.calc_log)
        dock = QDockWidget("Calculator", self)
        dock.setObjectName("calculator")
        dock.setWidget(w)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.calc_dock = dock

    def _act(self, tb, text, slot, key=None, checkable=False, tip=None):
        a = QAction(text, self)
        if key:
            a.setShortcut(QKeySequence(key))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        if tip:
            a.setToolTip(tip)
        tb.addAction(a)
        return a

    def _build_toolbar(self):
        tb = QToolBar("Viewer")
        tb.setObjectName("viewer")
        self.addToolBar(tb)
        self._act(tb, "Open…", self.open_files, "Ctrl+O", tip="Open SPICE raw files or a OLSim history")
        tb.addSeparator()
        self._act(tb, "Fit", self.fit, "F")
        self.zoom_box = self._act(tb, "Zoom Box", self._toggle_zoom_box, checkable=True,
                                  tip="Left drag draws a zoom box (otherwise it pans)")
        self.logx = self._act(tb, "Log X", lambda on: self._log("x", on), checkable=True)
        self.logy = self._act(tb, "Log Y", lambda on: self._log("y", on), checkable=True)
        tb.addSeparator()
        self._act(tb, "New Strip", self.new_strip, "Ctrl+N")
        self._act(tb, "Delete Strip", self.delete_strip)
        self._act(tb, "Clear", self.clear_all)
        tb.addSeparator()
        self._act(tb, "Cursor A", lambda: self.place_cursor("A"), "A")
        self._act(tb, "Cursor B", lambda: self.place_cursor("B"), "B")
        self._act(tb, "H Cursor", self.toggle_hcursor, "H", tip="A horizontal cursor on the active strip")
        self._act(tb, "Marker", self.place_marker, "M", tip="A marker at the nearest point of the nearest curve")
        self._act(tb, "Remove Cursors", self.remove_cursors)
        tb.addSeparator()
        self._act(tb, "Export PNG…", self.export_png)
        self._act(tb, "Export CSV…", self.export_csv)
        delete = QAction(self)
        delete.setShortcut(QKeySequence.Delete)
        delete.triggered.connect(self.delete_selected)
        self.addAction(delete)

    # ---- sources and browser --------------------------------------------------------------------
    def add_raw(self, path):
        path = Path(path)
        src = Source(path.name, lambda: rawfile.read(path))
        self.sources.append(src)
        self.refresh_browser()
        return src

    def add_history(self, history):
        """Every point of a OLSim history (engine.History) as a source."""
        added = []
        for p in history.points:
            if p["index"] in {s.index for s in self.sources if s.history is not None and s.history.path == history.path}:
                continue
            label = f"{history.name} / {p['index']}: {p['test']} {p['label']}"
            src = Source(label, (lambda h, i: lambda: h.plots(i))(history, p["index"]), p["variables"],
                         history, p["index"])
            self.sources.append(src)
            added.append(src)
        self.refresh_browser()
        return added

    def refresh_browser(self):
        self.tree.clear()
        self.calc_source.clear()
        groups = {}
        for si_, src in enumerate(self.sources):
            parent = self.tree
            if src.history is not None:
                if src.history.path not in groups:
                    g = QTreeWidgetItem(self.tree, [f"{src.history.name}  (OLSim)"])
                    g.setData(0, Qt.UserRole, ("history", str(src.history.path)))
                    groups[src.history.path] = g
                parent = groups[src.history.path]
            top = QTreeWidgetItem(parent, [src.label.split(" / ", 1)[-1]])
            top.setData(0, Qt.UserRole, ("source", si_))
            self.calc_source.addItem(src.label, si_)
            top.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self._apply_filter()

    def _expand(self, item):
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != "source" or item.childCount():
            return
        src = self.sources[data[1]]
        try:
            plots = src.plots
        except Exception as e:
            QTreeWidgetItem(item, [f"cannot read: {e}"])
            return
        self.tree.blockSignals(True)
        for p in plots:
            a = QTreeWidgetItem(item, [f"{p.kind}  ({len(p.x)} points)"])
            for name in p.signals(self.internal.isChecked()):
                s = QTreeWidgetItem(a, [name])
                s.setData(0, Qt.UserRole, ("signal", data[1], p.kind, name))
                s.setFlags(s.flags() | Qt.ItemIsUserCheckable)          # checked = visible on the plot
                s.setCheckState(0, Qt.Checked if self._shown((data[1], p.kind, name)) else Qt.Unchecked)
            a.setExpanded(True)
        self.tree.blockSignals(False)
        self._apply_filter()

    # ---- visibility -----------------------------------------------------------------------------
    def _shown(self, key):
        return any(c.visible for c in self.keyed.get(key, []))

    def _signal_items(self, key):
        found = []

        def walk(it):
            d = it.data(0, Qt.UserRole)
            if d and d[0] == "signal" and tuple(d[1:]) == key:
                found.append(it)
            for i in range(it.childCount()):
                walk(it.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return found

    def _sync(self, key):
        """The browser checkbox of a signal follows its curves."""
        if key is None:
            return
        self.tree.blockSignals(True)
        for it in self._signal_items(key):
            it.setCheckState(0, Qt.Checked if self._shown(key) else Qt.Unchecked)
        self.tree.blockSignals(False)

    def set_signal_visible(self, key, on, new_strip=False):
        """Show (plotting it the first time) or hide a browser signal - never a second copy."""
        curves = self.keyed.get(key, [])
        if on and not curves:
            self.plot_signal(*key, new_strip=new_strip)
            return
        for c in curves:
            c.strip.set_visible(c, on)
        self._sync(key)
        self.update_readout()

    def set_curve_visible(self, curve, on):
        curve.strip.set_visible(curve, on)
        self._sync(curve.key)
        self.update_readout()

    def forget(self, curve):
        """A curve was removed: drop it from the signal map (the browser checkbox follows)."""
        if curve.key in self.keyed:
            self.keyed[curve.key] = [c for c in self.keyed[curve.key] if c is not curve]
            if not self.keyed[curve.key]:
                del self.keyed[curve.key]
            self._sync(curve.key)

    def _tree_checked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "signal":
            self.set_signal_visible(tuple(data[1:]), item.checkState(0) == Qt.Checked)

    def _readout_checked(self, item):
        if item.column() != 0 or item.row() >= len(self._readout_curves):
            return
        self.set_curve_visible(self._readout_curves[item.row()], item.checkState() == Qt.Checked)

    def _apply_filter(self):
        pat = self.filter.text().strip().lower()
        glob = pat if any(c in pat for c in "*?[") else f"*{pat}*"

        def walk(item):
            visible_child = False
            for i in range(item.childCount()):
                visible_child |= walk(item.child(i))
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "signal":
                show = not pat or fnmatch.fnmatch(item.text(0).lower(), glob)
                item.setHidden(not show)
                return show
            item.setHidden(bool(pat) and item.childCount() > 0 and not visible_child)
            return visible_child or not pat

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _tree_double(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "signal":
            new = QApplication.keyboardModifiers() & Qt.ControlModifier
            self.set_signal_visible(tuple(data[1:]), True, new_strip=bool(new))

    def _tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item else None
        if not data or data[0] != "signal":
            return
        m = QMenu(self)
        m.addAction("Plot", lambda: self.plot_signal(data[1], data[2], data[3]))
        m.addAction("Plot in New Strip", lambda: self.plot_signal(data[1], data[2], data[3], new_strip=True))
        src = self.sources[data[1]]
        if src.history is not None:
            m.addAction("Plot Across All Points", lambda: self.plot_across(src.history, data[2], data[3]))
        sel = [i.data(0, Qt.UserRole) for i in self.tree.selectedItems()]
        sel = [d for d in sel if d and d[0] == "signal"] or [data]
        if len(sel) > 1:
            m.addAction(f"Plot {len(sel)} Selected, One Strip Each",
                        lambda: [self.plot_signal(d[1], d[2], d[3], new_strip=k > 0) for k, d in enumerate(sel)])
        m.addAction("Plot as Digital" + (f" ({len(sel)} lanes)" if len(sel) > 1 else ""),
                    lambda: self.plot_as_digital([(d[1], d[2], d[3]) for d in sel]))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ---- plotting -------------------------------------------------------------------------------
    def next_color(self):
        self._color += 1
        return self._color - 1

    def new_strip(self):
        plot = self.layout_widget.addPlot(row=len(self.strips), col=0)
        strip = Strip(self, plot)
        self.strips.append(strip)
        for name, x in self.cursor_x.items():
            if x is not None:
                self._cursor_line(strip, name, x)
        self._relink()
        self.set_active(strip)
        return strip

    def _relink(self):
        first = {}
        for s in self.strips:
            s.plot.setXLink(None)
            if s.xkind in first:
                s.plot.setXLink(first[s.xkind].plot)
            elif s.xkind:
                first[s.xkind] = s

    def set_active(self, strip):
        self.active = strip
        for s in self.strips:
            s.plot.getViewBox().setBorder(pg.mkPen(CANVAS["cursor"] if s is strip else CANVAS["grid"],
                                                  width=1.5 if s is strip else 0.5))

    def _scene_clicked(self, ev):
        for s in self.strips:
            if s.plot.sceneBoundingRect().contains(ev.scenePos()):
                self.set_active(s)
                return

    def delete_strip(self):
        if not self.active or len(self.strips) == 1:
            if self.active:
                self.active.clear()
            return
        s = self.active
        s.clear()                                      # (the browser checkboxes follow)
        self.layout_widget.removeItem(s.plot)
        self.strips.remove(s)
        for i, st in enumerate(self.strips):          # re-pack the rows
            self.layout_widget.removeItem(st.plot)
        for i, st in enumerate(self.strips):
            self.layout_widget.addItem(st.plot, row=i, col=0)
        self.set_active(self.strips[-1])
        self._relink()

    def clear_all(self):
        while len(self.strips) > 1:
            self.set_active(self.strips[-1])
            self.delete_strip()
        self.strips[0].clear()
        self._color = 0
        self.remove_cursors()
        self.update_readout()

    def _target_strip(self, xkind, new_strip):
        s = self.active
        if s is not None and not s.curves:              # an empty strip takes anything
            return s
        if new_strip or s is None or (s.xkind and s.xkind != xkind):
            s = self.new_strip()
        return s

    def plot_wave(self, wave: Waveform, label, xkind, unit="", new_strip=False, color=None, style=Qt.SolidLine,
                  complex_mode=None):
        """Plot a calculator Waveform (complex: dB magnitude, or phase with complex_mode="phase")."""
        y = wave.y
        if np.iscomplexobj(y):
            if complex_mode == "phase":
                y = np.degrees(np.unwrap(np.angle(y)))
                label, unit = f"phase({label})", "°"
            else:
                y = 20 * np.log10(np.maximum(np.abs(y), 1e-300))
                label, unit = f"dB20({label})", "dB"
        xunit = UNITS.get(wave.xname, "s" if wave.xname == "time" else "Hz" if wave.xname == "frequency" else "")
        s = self._target_strip(xkind, new_strip)
        c = s.add(wave.x, np.asarray(y, float), label, unit, xunit, xkind, color, style)
        if xkind == "ac" and not s.plot.getViewBox().state["logMode"][0]:
            s.plot.setLogMode(x=True, y=False)
        self._relink()
        if len(s.curves) == 1:
            s.plot.enableAutoRange()          # follows new curves until the user zooms or pans
        self.update_readout()
        return c

    def plot_signal(self, source_index, kind, name, new_strip=False, color=None, label=None):
        key = (source_index, kind, name)
        if self.keyed.get(key) and not new_strip:      # plotted already: show it again, no second copy
            self.set_signal_visible(key, True)
            return self.keyed[key][0]
        src = self.sources[source_index]
        w, p = src.wave(kind, name)
        unit = _unit_of(name, p.units[p.index(name)] if p.index(name) is not None else "")
        lab = label or (name if len(self.sources) == 1 else f"{name} [{src.label.split(' / ')[-1]}]")
        c = self.plot_wave(w, lab, kind, unit, new_strip, color)
        made = [c]
        if p.complex and kind == "ac":                 # the phase in a strip below the magnitude
            made.append(self.plot_wave(w, lab, kind, "°", new_strip=True, color=color, complex_mode="phase"))
        for m in made:
            m.key = key
            self.keyed.setdefault(key, []).append(m)
        self._sync(key)
        return c

    def plot_across(self, history, kind, name, new_strip=True):
        """The signal at every point of a history, overlaid."""
        first = True
        for i, src in enumerate(self.sources):
            if src.history is None or src.history.path != history.path:
                continue
            try:
                self.plot_signal(i, kind, name, new_strip=new_strip and first,
                                 label=f"{name} {src.label.split(' / ')[-1]}")
                first = False
            except (KeyError, StopIteration):
                continue

    def plot_output(self, history, output_name, indexes=None, new_strip=True):
        """A OLSim output (a waveform expression) at the given points (default all), overlaid."""
        self.add_history(history)
        first = True
        for p in history.points:
            if indexes is not None and p["index"] not in indexes:
                continue
            try:
                w = history.wave(p["index"], output_name)
            except (CalcError, StopIteration, KeyError) as e:
                self.statusBar().showMessage(f"{output_name} at point {p['index']}: {e}", 8000)
                continue
            if not isinstance(w, Waveform):
                continue
            kind = "ac" if w.xname == "frequency" else "dc" if w.xname not in ("time", "frequency") else "tran"
            self.plot_wave(w, f"{output_name} {p['label']}" if len(history.points) > 1 else output_name,
                           kind, _unit_of(w.name, ""), new_strip=new_strip and first)
            first = False

    def plot_xy(self, x, y, label, xname, xunit="", unit="", new_strip=False):
        """A parametric curve - a scalar output against a swept variable - with point markers."""
        kind = f"param:{xname}"
        s = self._target_strip(kind, new_strip)
        order = np.argsort(np.asarray(x, float))
        c = s.add(np.asarray(x, float)[order], np.asarray(y, float)[order], label, unit, xunit, kind, symbol="o")
        s.plot.setLabel("bottom", xname, units=xunit)
        s.plot.enableAutoRange()
        self._relink()
        self.update_readout()
        return c

    # ---- digital --------------------------------------------------------------------------------
    def plot_digital(self, lanes, errors=None, new_strip=True):
        """Logic lanes stacked in one strip, top to bottom. lanes: dicts with
            label, wave (Waveform), threshold                 - a bit
            label, waves [MSB..LSB], threshold                - a bus, shown in hex
            label, steps [(t, "0"|"1"|"X")]                   - expected values (dashed)
            label, bus_steps [(t, "A3"|"X")]                  - expected bus values (dashed)
        and an optional color. errors: [(t, label of the lane)] get red markers."""
        s = self.active if (self.active and not self.active.curves) else self.new_strip()
        s.plot.showGrid(x=True, y=False)
        ticks, by_label = [], {}
        n = len(lanes)
        t_end = max((float(ln["wave"].x[-1]) if "wave" in ln else float(ln["waves"][0].x[-1]) if "waves" in ln
                     else (ln.get("steps") or ln.get("bus_steps"))[-1][0] for ln in lanes), default=0.0)
        for k, ln in enumerate(lanes):
            base = (n - 1 - k) * 1.6
            color = ln.get("color") or COLORS[self.next_color() % len(COLORS)]
            if "wave" in ln:
                w = ln["wave"]
                y = base + (w.real_y > ln["threshold"]).astype(float)
                c = s.add(w.x, y, ln["label"], "", "s", "tran", color, legend=False)
                c.lane = base
            elif "waves" in ln:
                c = self._bus_lane(s, ln, base, color)
            elif "bus_steps" in ln:
                steps = ln["bus_steps"]
                segs = [(t, nxt[0], v) for (t, v), nxt in zip(steps, steps[1:] + [(t_end, None)])]
                c = self._band(s, segs, ln["label"], base, color, Qt.DashLine)
            else:
                xs, ys = [], []
                for (t, v), nxt in zip(ln["steps"], ln["steps"][1:] + [(t_end, None)]):
                    lvl = np.nan if v == "X" else base + (1.0 if v == "1" else 0.0)
                    xs += [t, nxt[0]]
                    ys += [lvl, lvl]
                c = s.add(np.array(xs), np.array(ys), ln["label"], "", "s", "tran", color, Qt.DashLine, legend=False)
                c.lane = base
            ticks.append((base + 0.5, ln["label"]))
            by_label[ln["label"]] = base
        s.plot.getAxis("left").setTicks([ticks, []])
        s.plot.getAxis("left").setWidth(110)
        s.plot.setLabel("left", "")
        if errors:
            xs = [t for t, lab in errors if lab in by_label]
            ys = [by_label[lab] + 0.5 for t, lab in errors if lab in by_label]
            s.plot.addItem(pg.ScatterPlotItem(xs, ys, symbol="x", size=14, pen=pg.mkPen(theme.C["fail"], width=2.5),
                                              brush=None))
        s.plot.setYRange(-0.4, n * 1.6, padding=0)
        s.plot.enableAutoRange(axis="x")
        self._relink()
        self.update_readout()
        return s

    def _bus_lane(self, s, ln, base, color):
        """A bus: the bits thresholded into hex values, drawn as a band with the value written in it."""
        waves = ln["waves"]
        x = waves[0].x
        bits = [np.interp(x, w.x, w.real_y) > ln["threshold"] for w in waves]
        val = np.zeros(len(x), dtype=np.int64)
        for b in bits:
            val = (val << 1) | b.astype(np.int64)
        change = np.nonzero(np.diff(val))[0] + 1
        starts = np.concatenate([[0], change])
        ends = np.concatenate([change, [len(x) - 1]])
        digits = max(1, (len(waves) + 3) // 4)
        segs = [(float(x[a]), float(x[b]) if b < len(x) - 1 else float(x[-1]) * 1.0000001, f"{val[a]:0{digits}X}")
                for a, b in zip(starts, ends)]
        return self._band(s, segs, ln["label"], base, color)

    def _band(self, s, segs, label, base, color, style=Qt.SolidLine):
        """A bus band [(t0, t1, text)] with crossings at the changes and the values written in it."""
        xs, ys = [], []
        span = (segs[-1][1] - segs[0][0]) if segs else 1.0
        for t0, t1, _ in segs:
            d = min((t1 - t0) * 0.1, span * 0.002)
            xs += [t0, t0 + d, t1 - d, t1, t1 - d, t0 + d, t0, np.nan]
            ys += [base + 0.5, base + 1, base + 1, base + 0.5, base, base, base + 0.5, np.nan]
        c = s.add(np.array(xs, float), np.array(ys, float), label, "", "s", "tran", color, style, legend=False)
        c.bus = segs
        for t0, t1, v in segs[:300]:
            if (t1 - t0) > span / 60:
                txt = pg.TextItem(v, color=color, anchor=(0.5, 0.5))
                txt.setPos((t0 + t1) / 2, base + 0.5)
                s.plot.addItem(txt)
        return c

    def plot_vector_check(self, history, index):
        """What a vector file drives and checks at one OLSim point: inputs, outputs as simulated,
        the expected outputs dashed, mismatches marked; buses in hex."""
        import json as _json
        from ..olsim import vectors
        p = history.points[index]
        setup = history.setup()
        test = setup.test(p["test"])
        if not test or not test.vectors:
            raise CalcError("this test has no vector file")
        plots = history.plots(index)
        tran = next((pl for pl in plots if pl.kind == "tran"), None)
        if tran is None:
            raise CalcError("no transient results at this point")
        ctx = Context(plots, p["variables"], "tran")
        errors = []
        ef = history.path / "points" / str(index) / "vector_errors.json"
        if ef.is_file():
            errors = _json.loads(ef.read_text())
        lanes, marks = [], []
        for vpath in test.vectors:
            f = Path(vpath) if Path(vpath).is_absolute() else setup.directory / vpath
            vf = vectors.parse(f)
            groups = {}
            for b in vf.bits:                        # buses: bits named x[i] in one column
                key = (b.name.split("[")[0], b.column) if "[" in b.name else (b.name, b.column)
                groups.setdefault(key, []).append(b)
            for (name, _col), bits in groups.items():
                vih, vil, voh, vol = vf.levels(bits[0], p["variables"])
                th = (vih + vil) / 2 if bits[0].io != "o" else (voh + vol) / 2
                try:
                    waves = [ctx.signal("v", b.name, "tran") for b in bits]
                except CalcError:
                    continue
                label = name if len(bits) == 1 else f"{name}[{len(bits) - 1}:0]"
                lanes.append({"label": label, "wave": waves[0], "threshold": th} if len(bits) == 1 else
                             {"label": label, "waves": waves, "threshold": th})
                if bits[0].io == "o":
                    if len(bits) == 1:
                        lanes.append({"label": f"{label} expected", "color": "#7d8696",
                                      "steps": list(zip(vf.times, bits[0].values))})
                    else:
                        digits = max(1, (len(bits) + 3) // 4)
                        steps = []
                        for k, t in enumerate(vf.times):
                            vals = [b.values[k] for b in bits]
                            steps.append((t, "X" if any(v in ("X", "Z") for v in vals)
                                          else f"{int(''.join(vals), 2):0{digits}X}"))
                        lanes.append({"label": f"{label} expected", "color": "#7d8696", "bus_steps": steps})
                    for e in errors:
                        if e["signal"] in {b.name for b in bits}:
                            marks.append((e["time"], label))
        if not lanes:
            raise CalcError("none of the vector file's signals are in the results")
        s = self.plot_digital(lanes, marks)
        s.plot.setTitle(f"vectors - point {index}: {p['label']}"
                        + (f"  -  {len(errors)} mismatch(es)" if errors else "  -  all outputs as expected"),
                        color=theme.C["fail"] if errors else theme.C["ok"])
        return s

    def plot_as_digital(self, items):
        """Browser selection [(source index, kind, name)] as logic lanes (threshold mid-range)."""
        lanes = []
        for si_, kind, name in items:
            w, _ = self.sources[si_].wave(kind, name)
            lo, hi = float(np.min(w.real_y)), float(np.max(w.real_y))
            lanes.append({"label": name, "wave": w, "threshold": (lo + hi) / 2})
        return self.plot_digital(lanes)

    def fit(self):
        for s in self.strips:
            s.plot.enableAutoRange()

    def _toggle_zoom_box(self, on):
        for s in self.strips:
            s.plot.getViewBox().setMouseMode(pg.ViewBox.RectMode if on else pg.ViewBox.PanMode)

    def _log(self, axis, on):
        if self.active:
            self.active.plot.setLogMode(**{axis: on})

    def select_curve(self, strip, item):
        if self.selected:
            c = self.selected[1]
            c.item.setPen(pg.mkPen(color=c.item.opts["pen"].color(), width=1.6))
        c = next(cv for cv in strip.curves if cv.item is item)
        c.item.setPen(pg.mkPen(color=c.item.opts["pen"].color(), width=3.2))
        self.selected = (strip, c)
        self.statusBar().showMessage(f"selected {c.label} (Delete removes it)", 5000)

    def delete_selected(self):
        if self.selected:
            strip, c = self.selected
            strip.remove(c)
            self.selected = None
            self.update_readout()

    # ---- cursors and markers --------------------------------------------------------------------
    def _mouse_moved(self, pos):
        self._mouse = pos
        for s in self.strips:
            if s.plot.sceneBoundingRect().contains(pos):
                p = s.plot.getViewBox().mapSceneToView(pos)
                x = 10 ** p.x() if s.plot.getViewBox().state["logMode"][0] else p.x()
                self.statusBar().showMessage(f"x = {fmt(x)}{s.xunit or ''}   y = {fmt(p.y())}")
                return

    def _mouse_x(self):
        if self._mouse is None:
            return None, None
        for s in self.strips:
            if s.plot.sceneBoundingRect().contains(self._mouse):
                vb = s.plot.getViewBox()
                p = vb.mapSceneToView(self._mouse)
                return s, (10 ** p.x() if vb.state["logMode"][0] else p.x())
        return None, None

    def _cursor_line(self, strip, name, x):
        line = strip.cursors.get(name)
        logx = strip.plot.getViewBox().state["logMode"][0]
        vx = math.log10(x) if logx and x > 0 else x
        if line is None:
            color = CANVAS["cursor"] if name == "A" else "#ff8a80"
            line = pg.InfiniteLine(pos=vx, angle=90, movable=True,
                                   pen=pg.mkPen(color, width=1.2, style=Qt.DashLine),
                                   label=name, labelOpts={"position": 0.95, "color": color})
            line.sigPositionChanged.connect(lambda ln, n=name, st=strip: self._cursor_dragged(n, st, ln))
            strip.plot.addItem(line, ignoreBounds=True)
            strip.cursors[name] = line
        else:
            line.blockSignals(True)
            line.setValue(vx)
            line.blockSignals(False)

    def _cursor_dragged(self, name, strip, line):
        logx = strip.plot.getViewBox().state["logMode"][0]
        x = 10 ** line.value() if logx else line.value()
        self.cursor_x[name] = x
        for s in self.strips:
            if s is not strip and s.xkind == strip.xkind:
                self._cursor_line(s, name, x)
        self.update_readout()

    def place_cursor(self, name):
        s, x = self._mouse_x()
        if s is None:
            s = self.active
            if not s or not s.curves:
                return
            xr = s.plot.getViewBox().viewRange()[0]
            vx = xr[0] + (0.33 if name == "A" else 0.66) * (xr[1] - xr[0])
            x = 10 ** vx if s.plot.getViewBox().state["logMode"][0] else vx
        self.cursor_x[name] = x
        for st in self.strips:
            if st.xkind == s.xkind or not st.curves:
                self._cursor_line(st, name, x)
        self.update_readout()

    def toggle_hcursor(self):
        s = self.active
        if s is None:
            return
        if s.hcursor is not None:
            s.plot.removeItem(s.hcursor)
            s.hcursor = None
            return
        yr = s.plot.getViewBox().viewRange()[1]
        s.hcursor = pg.InfiniteLine(pos=(yr[0] + yr[1]) / 2, angle=0, movable=True,
                                    pen=pg.mkPen("#4dd0c4", width=1.2, style=Qt.DashLine),
                                    label="y={value:.4g}", labelOpts={"position": 0.05, "color": "#4dd0c4"})
        s.plot.addItem(s.hcursor, ignoreBounds=True)

    def remove_cursors(self):
        for s in self.strips:
            for line in s.cursors.values():
                s.plot.removeItem(line)
            s.cursors = {}
            if s.hcursor is not None:
                s.plot.removeItem(s.hcursor)
                s.hcursor = None
        for strip, items in self.markers:
            for it in items:
                strip.plot.removeItem(it)
        self.markers = []
        self.cursor_x = {"A": None, "B": None}
        self.update_readout()

    def place_marker(self):
        s, x = self._mouse_x()
        if s is None or not s.curves:
            return
        vb = s.plot.getViewBox()
        my = vb.mapSceneToView(self._mouse).y()
        best = min(s.curves, key=lambda c: abs((c.at(x) or 0) - my))
        y = best.at(x)
        logx = vb.state["logMode"][0]
        vx = math.log10(x) if logx else x
        dot = pg.ScatterPlotItem([vx], [y], size=8, brush=pg.mkBrush(CANVAS["cursor"]), pen=None)
        txt = pg.TextItem(f"{best.label}\n{fmt(x)}{s.xunit or ''}, {fmt(y)}{best.unit}", color=CANVAS["text"],
                          anchor=(0, 1), fill=pg.mkBrush(theme.C["panel"]))
        txt.setPos(vx, y)
        s.plot.addItem(dot)
        s.plot.addItem(txt)
        self.markers.append((s, [dot, txt]))

    def update_readout(self):
        xa, xb = self.cursor_x["A"], self.cursor_x["B"]
        rows = [(s, c) for s in self.strips for c in s.curves if c.label]
        self._readout_curves = [c for _, c in rows]
        self.readout.blockSignals(True)
        self.readout.setRowCount(len(rows))
        for r, (s, c) in enumerate(rows):
            if not c.visible:
                vals = [c.label, "", "", "", "hidden"]
            elif c.lane is not None or c.bus is not None:
                vals = [c.label, c.text_at(xa), c.text_at(xb), "", ""]
            else:
                ya, yb = c.at(xa), c.at(xb)
                vals = [c.label, "" if ya is None else f"{fmt(ya)}{c.unit}", "" if yb is None else f"{fmt(yb)}{c.unit}",
                        "" if ya is None or yb is None else f"{fmt(yb - ya)}{c.unit}",
                        "" if ya is None or yb is None or xa == xb else f"slope {fmt((yb - ya) / (xb - xa))}"]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if col == 0:
                    item.setForeground(c.item.opts["pen"].color())
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if c.visible else Qt.Unchecked)
                self.readout.setItem(r, col, item)
        self.readout.blockSignals(False)
        unit = next((s.xunit for s in self.strips if s.cursors and s.xunit), "")
        parts = []
        if xa is not None:
            parts.append(f"A = {fmt(xa)}{unit}")
        if xb is not None:
            parts.append(f"B = {fmt(xb)}{unit}")
        if xa is not None and xb is not None and xa != xb:
            parts.append(f"B - A = {fmt(xb - xa)}{unit}")
            parts.append(f"1/(B - A) = {fmt(1 / abs(xb - xa))}" + ("Hz" if unit == "s" else ""))
        self.cursor_label.setText("   ".join(parts) or "cursors: press A / B over a strip")
        self.cursorsMoved.emit()

    # ---- calculator -----------------------------------------------------------------------------
    def calculate(self):
        expr = self.calc_expr.text().strip()
        if not expr:
            return
        idx = self.calc_source.currentData()
        if idx is None:
            self.calc_log.addItem("open results first")
            return
        src = self.sources[idx]
        kind = None
        try:
            val = evaluate(expr, src.context(kind))
        except CalcError as e:
            self.calc_log.addItem(f"{expr}  ->  error: {e}")
            self.calc_log.scrollToBottom()
            return
        if isinstance(val, Waveform):
            k = "ac" if val.xname == "frequency" else "tran" if val.xname == "time" else "dc"
            self.plot_wave(val, expr, k, _unit_of(val.name, ""))
            self.calc_log.addItem(f"{expr}  ->  plotted")
        else:
            self.calc_log.addItem(f"{expr}  =  {fmt(val, 6)}")
        self.calc_log.scrollToBottom()
        return val

    # ---- files ----------------------------------------------------------------------------------
    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open results", "", "SPICE raw (*.raw);;All files (*)")
        for f in files:
            self.add_raw(f)

    def export_png(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "waves.png", "PNG (*.png)")
        if path:
            ex = pg.exporters.ImageExporter(self.layout_widget.scene())
            ex.parameters()["width"] = max(1200, self.layout_widget.width())
            ex.export(str(path))
        return path

    def export_csv(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "waves.csv", "CSV (*.csv)")
        if not path:
            return None
        cols = [(c.label, c.x, c.y) for s in self.strips for c in s.curves]
        n = max((len(x) for _, x, _ in cols), default=0)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([h for lab, _, _ in cols for h in (f"x ({lab})", lab)])
            for i in range(n):
                w.writerow([v for _, x, y in cols for v in ((x[i], y[i]) if i < len(x) else ("", ""))])
        return path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme.apply(app)
    v = Viewer()
    for a in argv:
        p = Path(a)
        if p.is_dir() and (p / "history.json").is_file():
            from ..olsim.engine import History
            v.add_history(History.load(p))
        elif p.is_file():
            v.add_raw(p)
        else:
            print(f"openlayout waves: {a}: not a raw file or OLSim history", file=sys.stderr)
    v.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
