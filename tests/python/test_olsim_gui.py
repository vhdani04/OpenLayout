"""OLSim and the waveform viewer in the hub (offscreen Qt): a testbench schematic's olsim view,
variables copied from the cellview, a run across corners, the results table, plots, cursors,
the calculator and exports."""
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from openlayout.workarea import Workarea  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def hub(app, tmp_path):
    from openlayout.hub.main_window import MainWindow
    wa = Workarea.create(tmp_path / "wa", "cpu8")
    tb = wa.library("cpu8").path / "tb_inv"
    tb.mkdir()
    sch = (Path(os.environ["OPENLAYOUT_HOME"]) / "tests/xschem/tb_inv/tb_inv.sch").read_text()
    # value={vdd} as the property form stores it (braces escaped inside the .sch)
    (tb / "tb_inv.sch").write_text(sch.replace("name=VDD value=0.7", r"name=VDD value=\{vdd\}"))
    w = MainWindow(wa)
    yield w
    for m in getattr(w, "_olsims", {}).values():
        m._dirty = False
        m.close()
    w.close()


def wait_run(app, m, timeout=180):
    end = time.time() + timeout
    while time.time() < end and (m.run is None or m.run.running() or not m.a_run.isEnabled()):
        app.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        app.processEvents()


def test_olsim_in_the_hub(hub, app):
    cell = hub.workarea.library("cpu8").cell("tb_inv")
    hub.lm.select("cpu8", "tb_inv")
    assert hub.a_olsim.isEnabled()
    m = hub.open_olsim(cell)
    assert cell.view("olsim") is not None                      # created for the testbench
    assert m.t_lib.currentText() == "cpu8" and m.t_cell.currentText() == "tb_inv"

    # Variables > Copy From Cellview finds {vdd}
    m.copy_variables()
    names = [m.variables.item(r, 0).text() for r in range(m.variables.rowCount())]
    assert names == ["vdd"]
    m.variables.item(0, 1).setText("0.7")
    # a DC sweep instead of the default tran; the switching threshold as an output with a spec
    m.analyses.setRowCount(0)
    m.add_analysis.setCurrentIndex(m.add_analysis.findText("dc"))
    m._add_analysis(m.add_analysis.findText("dc"))
    m.analyses.item(0, 2).setText("source=VIN start=0 stop=0.7 step=5m")
    m._add_output('cross(v("out") - v("in"), 0)', "vm")
    m.outputs.item(m.outputs.rowCount() - 1, 3).setText("range 0.3 0.4")
    m._add_output('v("out")', "vtc", plot=True)
    m._add_pvt()                                                  # ss / ff / tt / ss corners from vdd
    assert m.corners.rowCount() == 4
    m.start_run()
    wait_run(app, m)
    h = m.history
    assert h is not None and h.data["status"] == "done" and len(h.points) == 5
    vm = [h.result(p["index"])["vm"] for p in h.points]
    assert all(0.25 < r["value"] < 0.45 for r in vm), vm
    assert vm[0]["pass"] is True                                  # nominal
    assert "ignored" in " ".join(h.data["notes"])                 # the schematic's .control block
    # the results table: outputs x points, the status row first
    assert m.results.rowCount() == 3 and m.results.columnCount() == 3 + 5
    assert m.results.item(1, 0).text() == "vm" and m.results.item(0, 3).text() == "done"
    assert "pass" in m.summary.text()
    # auto-plot: the vtc output at every point, overlaid in the shared viewer
    v = hub.viewer()
    assert sum(len(s.curves) for s in v.strips) == 5
    # the setup was saved with the run and reloads
    from openlayout.olsim.setup import Setup
    s = Setup.load(cell.view("olsim").path)
    assert s.variables == {"vdd": "0.7"} and s.tests[0].analyses[0].type == "dc" and len(s.corners) == 4


def test_viewer_cursors_calculator_export(hub, app, tmp_path):
    from openlayout.olsim.engine import Run
    from openlayout.olsim.setup import Analysis, Output, Setup
    from openlayout.olsim.setup import Test as MTest
    (tmp_path / "rc.sp").write_text("* RC step\nV1 in 0 pwl(0 0 10p 0 11p 1)\nR1 in out 1k\nC1 out 0 10f\n")
    s = Setup(tests=[MTest("t", {"netlist": "rc.sp"}, [Analysis("tran", True, {"step": "0.1p", "stop": "100p"})])],
              outputs=[Output("t", "out", 'v("out")', plot=True)], jobs=1)
    s.path = str(tmp_path / "rc.olsim")
    h = Run(s, tmp_path / "res").run()
    v = hub.viewer()
    v.clear_all()
    v.plot_output(h, "out")
    src = next(i for i, x in enumerate(v.sources) if x.history is not None and x.history.path == h.path)
    v.plot_signal(src, "tran", "v(in)")
    strip = v.strips[0]
    assert len(strip.curves) == 2 and strip.xunit == "s"
    # cursors at 10 ps (step) and 20 ps (one RC later): the readout shows 1 - 1/e
    v.cursor_x.update({"A": 10.5e-12, "B": 20.5e-12})
    for name, x in v.cursor_x.items():
        v._cursor_line(strip, name, x)
    v.update_readout()
    out_row = next(r for r in range(v.readout.rowCount()) if v.readout.item(r, 0).text().startswith("out"))
    assert v.readout.item(out_row, 2).text().startswith("6")      # ~632 mV
    assert "B - A = 10ps" in v.cursor_label.text()
    # the calculator: a number, and a waveform it plots
    v.calc_source.setCurrentIndex(v.calc_source.findData(src))
    v.calc_expr.setText('cross(v("out"), 0.632) - cross(v("in"), 0.5)')
    tau = v.calculate()
    assert tau == pytest.approx(10e-12, rel=0.05)
    v.calc_expr.setText('v("in") - v("out")')
    v.calculate()
    assert len(strip.curves) == 3
    # browser: the history, its point, the signals (internal device nodes hidden)
    assert v.tree.topLevelItemCount() >= 1
    png, csv = v.export_png(str(tmp_path / "w.png")), v.export_csv(str(tmp_path / "w.csv"))
    assert Path(png).stat().st_size > 5000
    head = Path(csv).read_text().splitlines()[0]
    assert "out" in head and "v(in)" in head
    # delete a curve, new strips, clear
    v.select_curve(strip, strip.curves[-1].item)
    v.delete_selected()
    assert len(strip.curves) == 2
    v.new_strip()
    assert len(v.strips) == 2
    v.clear_all()
    assert len(v.strips) == 1 and not v.strips[0].curves


def test_vector_check_and_parametric_plots(hub, app, tmp_path):
    from openlayout.hub.olsim_window import OLSimWindow
    from openlayout.olsim.engine import Run
    from openlayout.olsim.setup import Analysis, Output, Setup
    from openlayout.olsim.setup import Test as MTest
    lines = ["* 4-bit inverter bank", "Vdd vdd 0 0.7"]
    for i in range(4):
        lines += [f"N{i}a q[{i}] d[{i}] 0 0 nmos_rvt l=20n nfin=2", f"N{i}b q[{i}] d[{i}] vdd vdd pmos_rvt l=20n nfin=2",
                  f"C{i} q[{i}] 0 {{cl}}"]
    (tmp_path / "bank.sp").write_text("\n".join(lines) + "\n")
    (tmp_path / "bank.vec").write_text("radix 4 4\nio i o\nvname d[3:0] q[3:0]\ntunit ps\nperiod 100\nvih 0.7\n"
                                       "0 F\n5 A\nA 5\nC 7\n")              # the last expected value is wrong
    s = Setup(tests=[MTest("vec", {"netlist": "bank.sp"}, [Analysis("tran", True, {"step": "1p", "stop": "400p"})],
                           ["bank.vec"])],
              variables={"cl": "0.5f 1f 2f"},
              outputs=[Output("vec", "tq0", 'delay(v("d[0]"), v("q[0]"), 0.35, 0.35, "rise", "fall")')], jobs=3)
    s.save(tmp_path / "bank.olsim")
    m = OLSimWindow(tmp_path / "bank.olsim", None, tmp_path / "res", viewer=hub.viewer())
    m.history = Run(Setup.load(tmp_path / "bank.olsim"), tmp_path / "res").run()
    m.show_results()
    v = hub.viewer()
    v.clear_all()
    # the vector check: buses in hex, the expected bus dashed, the mismatch marked
    m.plot_vectors(0)
    lanes = {c.label: c for c in v.strips[0].curves}
    assert set(lanes) == {"d[3:0]", "q[3:0]", "q[3:0] expected"}
    stable = [v_ for t0, t1, v_ in lanes["q[3:0]"].bus if t1 - t0 > 5e-12]   # (bits switch a few ps apart)
    assert stable == ["F", "A", "5", "3"]
    assert [seg[2] for seg in lanes["q[3:0] expected"].bus] == ["F", "A", "5", "7"]
    assert "1 mismatch" in v.strips[0].plot.titleLabel.text
    # tq0 against the swept load, one curve (one corner); axes in s and F
    m.plot_vs("tq0", "cl")
    c = v.strips[-1].curves[-1]
    assert list(c.x) == pytest.approx([0.5e-15, 1e-15, 2e-15]) and c.y[0] < c.y[1] < c.y[2]
    assert v.strips[-1].xkind == "param:cl" and c.unit == "s"
    m._dirty = False
    m.close()


def test_testbench_hierarchy_and_picker(hub, app, monkeypatch):
    """OLSim on a circuit offers it a testbench (supply source, loads, vectors); the hierarchy
    chooses schematic / extracted per cell; Select on Schematic adds what is selected in xschem."""
    from PySide6.QtWidgets import QMessageBox
    from openlayout.hub.olsim_dialogs import HierarchyDialog, SchematicPicker
    from openlayout.symbolgen import make_symbol
    wa = hub.workarea
    d = wa.library("cpu8").path / "inv2"
    d.mkdir()
    (d / "inv2.sch").write_text((Path(os.environ["OPENLAYOUT_HOME"]) / "tests/klayout/inv_globals.sch").read_text())
    make_symbol(d / "inv2.sch")
    inv2 = wa.library("cpu8").cell("inv2")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = hub.open_olsim(inv2)
    tb = wa.library("cpu8").cell("tb_inv2")
    assert tb is not None and tb.view("olsim") and w.setup_path == tb.view("olsim").path
    sch = tb.view("schematic").path.read_text()
    assert r"{name=VDD value=\{vdd\}}" in sch and "{cpu8/inv2/inv2.sym}" in sch and "capa.sym" in sch
    s = w.setup
    assert s.variables == {"vdd": "0.7", "cload": "1f"} and s.tests[0].vectors == ["tb_inv2.vec"]
    assert s.outputs == [] and w.outputs.rowCount() == 0          # blank: the user picks the outputs
    # the expected output filled in (Z = not A), then a run: the vectors pass, the delays come out
    vec = tb.path / "tb_inv2.vec"
    vec.write_text("\n".join(l[:-1] + ("1" if l.split()[0] == "0" else "0") if l.startswith("  ") else l
                             for l in vec.read_text().splitlines()) + "\n")
    w.start_run()
    wait_run(app, w)
    r = w.history.result(0)
    assert r["vector errors"]["value"] == 0, r
    # the hierarchy: inv2 simulates its schematic until it has a PEX netlist
    t = w.setup.test("tran")
    dlg = HierarchyDialog(w, w._netlist_run(), t, wa)
    (entry, combo), = dlg.rows
    assert entry == "cpu8/inv2" and not combo.model().item(1).isEnabled()
    pex = wa.verify_dir(inv2) / "inv2.pex.spice"
    pex.parent.mkdir(parents=True)
    pex.write_text(".subckt inv2 A Z\nN1 Z A VSS VSS nmos_rvt l=20n nfin=2\nN2 Z A VDD VDD pmos_rvt l=20n nfin=2\n"
                   "C1 Z VSS 0.1f\n.ends\n")
    dlg = HierarchyDialog(w, w._netlist_run(), t, wa)
    (entry, combo), = dlg.rows
    assert combo.model().item(1).isEnabled()
    combo.setCurrentIndex(1)
    assert dlg.extracted() == ["cpu8/inv2"]

    # Select on Schematic: what xschem reports as selected becomes plotted outputs (once)
    class FakeXschem:
        def __init__(self):
            self.sent = []

        def ensure_started(self):
            pass

        def open(self, view):
            self.sent.append(f"open {view.path.name}")

        def send(self, tcl, timeout=5):
            self.sent.append(tcl)
            return {"xschem selected_wire": "{Z} {#net3}", "xschem selected_set": "{l1} {VDD}",
                    "xschem getprop instance {l1} lab": "A"}.get(tcl, "")

    fake = FakeXschem()
    before = w.outputs.rowCount()
    picker = SchematicPicker(w, fake, lambda e, n: w._add_output(e, n, plot=True), {'v("Z")'})
    picker.start(tb.view("schematic"))
    picker.poll()
    picker.poll()
    added = [w.outputs.item(r, 2).text() for r in range(before, w.outputs.rowCount())]
    assert added == ['v("net3")', 'v("A")', 'i("VDD")'] and "open tb_inv2.sch" in fake.sent
    shown = [picker.list.item(i).text() for i in range(picker.list.count())]
    assert any("Z" in x and "already an output" in x for x in shown)       # a click never does nothing
    picker.close()


def test_viewer_visibility_checkboxes(hub, app, tmp_path):
    from openlayout.olsim.engine import Run
    from openlayout.olsim.setup import Analysis, Setup
    from openlayout.olsim.setup import Test as MTest
    (tmp_path / "rc.sp").write_text("* RC\nV1 in 0 pwl(0 0 10p 0 11p 1)\nR1 in out 1k\nC1 out 0 10f\n")
    s = Setup(tests=[MTest("t", {"netlist": "rc.sp"}, [Analysis("tran", True, {"step": "0.1p", "stop": "50p"})])])
    s.path = str(tmp_path / "rc.olsim")
    h = Run(s, tmp_path / "res").run()
    v = hub.viewer()
    v.clear_all()
    v.add_history(h)
    src = next(i for i, x in enumerate(v.sources) if x.history is not None and x.history.path == h.path)
    top = next(v.tree.topLevelItem(i) for i in range(v.tree.topLevelItemCount())
               if v.tree.topLevelItem(i).text(0).startswith(h.name))
    point = top.child(0)
    v._expand(point)
    out_item = next(point.child(0).child(i) for i in range(point.child(0).childCount())
                    if point.child(0).child(i).text(0) == "v(out)")
    assert out_item.checkState(0) == Qt.Unchecked
    v._tree_double(out_item, 0)
    v._tree_double(out_item, 0)                          # a second double-click adds no copy
    curves = [c for st in v.strips for c in st.curves]
    assert len(curves) == 1 and out_item.checkState(0) == Qt.Checked
    out_item.setCheckState(0, Qt.Unchecked)              # untick: hidden, not deleted
    assert not curves[0].visible and not curves[0].item.isVisible() and len(v.strips[0].curves) == 1
    out_item.setCheckState(0, Qt.Checked)
    assert curves[0].visible
    # the readout's checkbox does the same, and the browser follows
    row = v._readout_curves.index(curves[0])
    v.readout.item(row, 0).setCheckState(Qt.Unchecked)
    assert not curves[0].visible and out_item.checkState(0) == Qt.Unchecked
    # a curve removed: the browser checkbox clears
    v.readout.item(row, 0).setCheckState(Qt.Checked)
    v.select_curve(v.strips[0], curves[0].item)
    v.delete_selected()
    assert out_item.checkState(0) == Qt.Unchecked and (src, "tran", "v(out)") not in v.keyed


def test_outputs_delete_key_and_xschem_fallback(hub, app):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from openlayout.hub.olsim_window import OLSimWindow
    from openlayout.hub.olsim_dialogs import AttachedXschem
    from openlayout.tools import XschemBridge
    cell = hub.workarea.library("cpu8").cell("tb_inv")
    w = OLSimWindow(cell.path / "x.olsim", hub.workarea)
    w._add_output('v("a")', "a")
    w._add_output('v("b")', "b")
    w.outputs.selectRow(0)
    w.outputs.setFocus()
    for a in w.outputs.actions():                      # the Delete shortcut
        if a.shortcut().toString() in ("Del", "Delete"):
            a.trigger()
    assert w.outputs.rowCount() == 1 and w.outputs.item(0, 1).text() == "b"
    w.outputs.setCurrentCell(0, 1)
    w.outputs.clearSelection()
    w._remove_rows(w.outputs)                         # nothing selected: the current row
    assert w.outputs.rowCount() == 0
    # Select on Schematic uses the hub's xschem when the session names one that answers
    assert isinstance(AttachedXschem(hub.workarea, 1), XschemBridge) and not AttachedXschem(hub.workarea, 1).running
    import json
    s = hub.workarea.session()
    hub.workarea.session_file.write_text(json.dumps({**s, "xschem_port": 1}))   # nothing listens there
    assert type(w.xschem()) is XschemBridge           # falls back to its own xschem
    assert "xschem_port" in s                         # the hub writes its port
    w._dirty = False
    w.close()


def test_viewer_drag_merges_strips(app):
    import numpy as np
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from openlayout.hub.waveview import Viewer
    from openlayout.olsim.calc import Waveform
    v = Viewer()
    v.resize(1200, 800)
    v.show()
    t = np.linspace(0, 1e-9, 1001)
    v.plot_wave(Waveform(t, np.sin(t * 2e10) * 0.35 + 0.35, "a", "time"), "a", "tran", "V")
    v.new_strip()
    v.plot_wave(Waveform(t, np.cos(t * 2e10) * 0.35 + 0.35, "b", "time"), "b", "tran", "V")
    for _ in range(20):
        app.processEvents()
    area, vb = v.layout_widget, v.strips[1].plot.getViewBox()
    x = 0.4e-9
    start = area.mapFromScene(vb.mapViewToScene(QPointF(x, float(np.cos(x * 2e10) * 0.35 + 0.35))))
    end = area.mapFromScene(v.strips[0].plot.sceneBoundingRect().center())
    assert v.curve_at(vb.mapViewToScene(QPointF(x, float(np.cos(x * 2e10) * 0.35 + 0.35)))) is not None

    def send(kind, pos, buttons):
        QApplication.sendEvent(area.viewport(), QMouseEvent(kind, QPointF(pos), QPointF(area.viewport().mapToGlobal(pos)),
                                                            Qt.LeftButton, buttons, Qt.NoModifier))
        app.processEvents()

    send(QEvent.MouseButtonPress, start, Qt.LeftButton)
    send(QEvent.MouseMove, (start + end) / 2, Qt.LeftButton)
    send(QEvent.MouseMove, end, Qt.LeftButton)
    send(QEvent.MouseButtonRelease, end, Qt.NoButton)
    assert len(v.strips) == 1 and [c.label for c in v.strips[0].curves] == ["a", "b"]
    # an AC curve cannot go onto a time axis
    f = np.logspace(6, 9, 50)
    c = v.plot_wave(Waveform(f, 1 / (1 + 1j * f / 1e8), "h", "frequency"), "h", "ac", new_strip=True)
    assert v.move_curve(c, v.strips[0]) is None and len(v.strips) == 2
    v.close()


def test_raw_file_in_viewer(app, tmp_path):
    import subprocess
    from openlayout.hub.waveview import Viewer
    (tmp_path / "t.sp").write_text("* ac\nV1 a 0 ac 1\nR1 a b 1k\nC1 b 0 1f\n.ac dec 10 1e6 1e13\n.end\n")
    subprocess.run(["ngspice", "-b", "-r", "t.raw", "t.sp"], cwd=tmp_path, capture_output=True, timeout=120)
    v = Viewer()
    v.add_raw(tmp_path / "t.raw")
    top = v.tree.topLevelItem(0)
    v._expand(top)
    sigs = [top.child(0).child(i).text(0) for i in range(top.child(0).childCount())]
    assert "v(b)" in sigs
    v.plot_signal(0, "ac", "v(b)")
    # AC: dB magnitude on a log axis, the phase in a strip below
    assert len(v.strips) == 2 and v.strips[0].curves[0].unit == "dB" and v.strips[1].curves[0].unit == "°"
    assert v.strips[0].plot.getViewBox().state["logMode"][0]
    assert v.strips[0].curves[0].y[0] == pytest.approx(0, abs=0.01)
    v.close()
