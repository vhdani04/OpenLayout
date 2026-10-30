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
    wa = Workarea.create(tmp_path / "wa", "testlib")
    tb = wa.library("testlib").path / "tb_inv"
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
    cell = hub.workarea.library("testlib").cell("tb_inv")
    hub.lm.select("testlib", "tb_inv")
    assert hub.a_olsim.isEnabled()
    m = hub.open_olsim(cell)
    assert cell.view("olsim") is not None                      # created for the testbench
    assert m.t_lib.currentText() == "testlib" and m.t_cell.currentText() == "tb_inv"

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
    from openlayout.hub.olsim_dialogs import SchematicPicker
    from openlayout.olsim.config import Config, Netlist
    from openlayout.symbolgen import make_symbol
    wa = hub.workarea
    d = wa.library("testlib").path / "inv2"
    d.mkdir()
    (d / "inv2.sch").write_text((Path(os.environ["OPENLAYOUT_HOME"]) / "tests/klayout/inv_globals.sch").read_text())
    make_symbol(d / "inv2.sch")
    inv2 = wa.library("testlib").cell("inv2")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = hub.open_olsim(inv2)
    tb = wa.library("testlib").cell("tb_inv2")
    assert tb is not None and tb.view("olsim") and w.setup_path == tb.view("olsim").path
    sch = tb.view("schematic").path.read_text()
    assert r"{name=VDD value=\{vdd\}}" in sch and "{testlib/inv2/inv2.sym}" in sch and "capa.sym" in sch
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
    # the hierarchy: the testbench's config view; inv2 simulates its schematic until it has a PEX netlist
    assert tb.view("config") is not None and w.setup.test("tran").design.get("view") == "config"
    assert "config testlib/tb_inv2" in w.t_hier.text()
    ed = w.edit_hierarchy()
    assert ed is not None and ed.net is not None
    x1 = ed.tree.topLevelItem(0)
    assert (x1.text(0), x1.text(1), x1.text(3)) == ("X1", "inv2", "schematic")
    ed.cells.cellWidget(0, 2).setCurrentText("extracted")          # no PEX netlist yet: flagged
    assert ed.tree.topLevelItem(0).text(3) == "error" and "without a PEX netlist" in ed.summary.text()
    pex = wa.verify_dir(inv2) / "inv2.pex.spice"
    pex.parent.mkdir(parents=True)
    pex.write_text(".subckt inv2 Z A VSS VDD\nN1 Z A VSS VSS nmos_rvt l=20n nfin=2\n"
                   "N2 Z A VDD VDD pmos_rvt l=20n nfin=2\nC1 Z VSS 0.1f\n.ends\n")
    ed.rescan()
    assert ed.tree.topLevelItem(0).text(3) == "extracted"
    text = ed.netlist()
    assert "* inv2: extracted (PEX inv2.pex.spice)" in text and sorted(Netlist(text).subckts["inv2"].ports) == ["A", "Z"]
    ed.save()
    assert Config.load(tb.view("config").path).cells == {"testlib/inv2": "extracted"}
    assert "inv2 extracted" in w.t_hier.text()
    w.start_run()                                      # the run simulates what the config says
    wait_run(app, w)
    assert w.history.result(0)["vector errors"]["value"] == 0, w.history.result(0)
    assert any("inv2 extracted (inv2.pex.spice): X1" in n for n in w.history.data["notes"]), w.history.data["notes"]
    # an instance binding beats the cell's
    ed.tree.itemWidget(ed.tree.topLevelItem(0), 2).setCurrentText("schematic")
    assert ed.tree.topLevelItem(0).text(3) == "schematic" and ed.cfg.instances == {"X1": "schematic"}
    ed._dirty = False
    ed.close()
    # a design given as the cell's schematic file is the library cell; its config is pointed out
    t = w.setup.test("tran")
    t.design = {"schematic": str(tb.view("schematic").path)}
    w._show_test()
    assert t.design == {"lib": "testlib", "cell": "tb_inv2"} and w.t_view.currentText() == "schematic"
    assert "has a config view" in w.t_hier.text() and "inv2 extracted" in w.t_hier.text()
    w._dirty = False

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
    assert len(v.strips) == 1 and v.active is v.strips[0]        # the only strip stays, empty


def test_viewer_no_empty_strips(app):
    import numpy as np
    from openlayout.hub.waveview import Viewer
    from openlayout.olsim.calc import Waveform
    v = Viewer()
    t = np.linspace(0, 1e-9, 101)
    a = v.plot_wave(Waveform(t, t, "a", "time"), "a", "tran", "V")
    b = v.plot_wave(Waveform(t, -t, "b", "time"), "b", "tran", "V", new_strip=True)
    c = v.plot_wave(Waveform(t, 2 * t, "c", "time"), "c", "tran", "V", new_strip=True)
    assert len(v._packed) == 3
    v.set_curve_visible(b, False)                     # all hidden: the strip folds away ...
    assert v._packed == [a.strip, c.strip] and len(v.strips) == 3
    assert v.strip_at(b.strip.plot.sceneBoundingRect().center()) is not b.strip
    v.set_curve_visible(b, True)                      # ... and comes back in its place
    assert v._packed == [a.strip, b.strip, c.strip]
    v.select_curve(b.strip, b.item)
    v.delete_selected()                               # its last curve deleted: the strip goes
    assert v.strips == [a.strip, c.strip] == v._packed
    s = v.new_strip()                                 # a new strip waits for the next signal ...
    assert len(v.strips) == 3 and v.active is s
    v.set_active(a.strip)
    v.plot_wave(Waveform(t, t * t, "d", "time"), "d", "tran", "V")
    assert s not in v.strips and len(v.strips) == 2   # ... and goes once it is passed over
    v.set_curve_visible(a, False)
    v.set_curve_visible(c, False)
    v.strips[0].curves[-1].strip.set_visible(v.strips[0].curves[-1], False)
    v._tidy()
    assert v._packed == [] and v.active is None       # nothing shown: no plots at all
    e = v.plot_wave(Waveform(t, t, "e", "time"), "e", "tran", "V", new_strip=True)
    assert v._packed == [e.strip]
    v.close()


def test_outputs_delete_key_and_xschem_fallback(hub, app):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from openlayout.hub.olsim_window import OLSimWindow
    from openlayout.hub.olsim_dialogs import AttachedXschem
    from openlayout.tools import XschemBridge
    cell = hub.workarea.library("testlib").cell("tb_inv")
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


def _viewer_with(app, n=3):
    import numpy as np
    from openlayout.hub.waveview import Viewer
    from openlayout.olsim.calc import Waveform
    v = Viewer()
    v.resize(1200, 900)
    v.show()
    t = np.linspace(0, 1e-9, 1001)
    curves = [v.plot_wave(Waveform(t, np.sin(t * (k + 1) * 1e10) * 0.35 + 0.35, f"s{k}", "time"), f"s{k}", "tran", "V",
                          new_strip=k > 0) for k in range(n)]
    for _ in range(20):
        app.processEvents()
    return v, curves


def _drag(app, area, start, end, modifiers=Qt.NoModifier):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    def send(kind, pos, buttons):
        QApplication.sendEvent(area.viewport(), QMouseEvent(kind, QPointF(pos), QPointF(area.viewport().mapToGlobal(pos)),
                                                            Qt.LeftButton, buttons, modifiers))
        app.processEvents()
    send(QEvent.MouseButtonPress, start, Qt.LeftButton)
    for f in (0.25, 0.5, 0.75):
        send(QEvent.MouseMove, start + (end - start) * f, Qt.LeftButton)
    send(QEvent.MouseMove, end, Qt.LeftButton)
    send(QEvent.MouseButtonRelease, end, Qt.NoButton)


def test_viewer_legend_outside(app):
    v, (a, b, c) = _viewer_with(app)
    for s in v.strips:
        leg, view = s.legend.sceneBoundingRect(), s.plot.getViewBox().sceneBoundingRect()
        assert leg.left() >= view.right() - 1, (leg, view)          # right of the data, not over it
        assert v.strip_at(leg.center()) is s                         # and still part of its strip
    assert [lab.text for _, lab in a.strip.legend.items] == ["s0"]
    v.set_curve_visible(a, False)                                    # hidden: off the legend too
    assert a.strip.legend.items == [] and len(b.strip.legend.items) == 1
    v.close()


def test_viewer_drag_strip_to_another_row(app):
    v, (a, b, c) = _viewer_with(app)
    area = v.layout_widget
    assert [s.curves[0].label for s in v._packed] == ["s0", "s1", "s2"]
    ax = c.strip.plot.getAxis("left")
    grip = ax.parentItem().mapRectToScene(ax.geometry()).center()
    assert v.axis_handle_at(grip) is c.strip
    assert v.axis_handle_at(c.strip.plot.getViewBox().sceneBoundingRect().center()) is None   # the grid is not
    top = a.strip.plot.sceneBoundingRect()
    _drag(app, area, area.mapFromScene(grip), area.mapFromScene(pg_point(top.center().x(), top.top() + 5)))
    assert [s.curves[0].label for s in v._packed] == ["s2", "s0", "s1"]    # above the strip it hit
    assert all(len(s.curves) == 1 for s in v.strips)                       # moved, not merged
    ax = c.strip.plot.getAxis("left")
    grip = ax.parentItem().mapRectToScene(ax.geometry()).center()
    bottom = b.strip.plot.sceneBoundingRect()
    _drag(app, area, area.mapFromScene(grip), area.mapFromScene(pg_point(bottom.center().x(), bottom.bottom() - 5)))
    assert [s.curves[0].label for s in v._packed] == ["s0", "s1", "s2"]    # below it
    v.close()


def test_viewer_ctrl_drag_zoom_box(app):
    v, (a, b, c) = _viewer_with(app)
    area, vb = v.layout_widget, b.strip.plot.getViewBox()
    from PySide6.QtCore import QPointF
    p0 = area.mapFromScene(vb.mapViewToScene(QPointF(0.2e-9, 0.6)))
    p1 = area.mapFromScene(vb.mapViewToScene(QPointF(0.4e-9, 0.2)))
    _drag(app, area, p0, p1, Qt.ControlModifier)
    for _ in range(10):
        app.processEvents()
    (x0, x1), (y0, y1) = vb.viewRange()
    assert x0 == pytest.approx(0.2e-9, rel=0.05) and x1 == pytest.approx(0.4e-9, rel=0.05), (x0, x1)
    assert y0 == pytest.approx(0.2, abs=0.02) and y1 == pytest.approx(0.6, abs=0.02), (y0, y1)
    assert a.strip.plot.getViewBox().viewRange()[0] == pytest.approx([x0, x1])    # x axes linked
    assert vb.state["mouseMode"] == vb.PanMode                                    # and back to panning
    v.close()


def test_viewer_global_range(app):
    v, (a, b, c) = _viewer_with(app)
    v.refresh_overview()
    assert v.region.isVisible() and v.overview.height() > 0
    v.region.setRegion((0.25e-9, 0.5e-9))                     # the slider sets every strip ...
    app.processEvents()
    for s in v._packed:
        assert s.plot.getViewBox().viewRange()[0] == pytest.approx([0.25e-9, 0.5e-9], rel=1e-6)
    b.strip.plot.setXRange(0.1e-9, 0.3e-9, padding=0)          # ... and follows a zoom in any strip
    app.processEvents()
    assert list(v.region.getRegion()) == pytest.approx([0.1e-9, 0.3e-9], rel=1e-6)
    v.fit()
    for _ in range(5):
        app.processEvents()
    assert v.region.getRegion()[0] == pytest.approx(0, abs=1e-11) and v.region.getRegion()[1] == pytest.approx(1e-9, rel=0.05)
    v.close()


def pg_point(x, y):
    from PySide6.QtCore import QPointF
    return QPointF(x, y)


def test_viewer_long_legends_keep_every_strip(app):
    """a sweep of 41 points overlaid in each of 3 strips: the legends are long, the strips stay"""
    import numpy as np
    from openlayout.hub.waveview import Viewer
    from openlayout.olsim.calc import Waveform
    v = Viewer()
    v.resize(1300, 820)
    v.show()
    t = np.linspace(0, 1e-9, 201)
    for k, name in enumerate(("D", "CLK", "Q")):
        for i in range(41):
            v.plot_wave(Waveform(t, np.sin(t * 1e10 + i) * 0.35 + 0.35, name, "time"), f"{name} tdata={i}p",
                        "tran", "V", new_strip=(i == 0 and k > 0))
    for _ in range(30):
        app.processEvents()
    area = v.layout_widget.viewport().rect()
    assert len(v._packed) == 3
    for s in v._packed:
        r = v.layout_widget.mapFromScene(s.plot.sceneBoundingRect()).boundingRect()
        assert area.contains(r.center()) and r.height() < area.height() / 2, (r, area)
        leg, view = s.legend.sceneBoundingRect(), s.plot.getViewBox().sceneBoundingRect()
        assert leg.left() >= view.right() - 1
    v.close()


def test_viewer_sweep_groups(app):
    """a net across sweep points: one legend row with a dropdown list; a net the same at every point
    (the clock) is plotted once"""
    import numpy as np
    from openlayout.hub.waveview import Viewer
    from openlayout.olsim.calc import Waveform
    v = Viewer()
    v.resize(1300, 820)
    v.show()
    v.add_history = lambda h: None
    t = np.linspace(0, 1e-9, 201)

    class H:
        points = [{"index": i, "label": f"Nominal tdata={i}p"} for i in range(3)]

        def wave(self, index, name):
            if name == "CLK":                     # the same PWL clock, sampled differently per run
                bp_t = [0, 1e-10, 1.1e-10, 2e-10, 2.1e-10, 3e-10, 3.1e-10, 1e-9]
                bp_v = [0, 0, 0.7, 0.7, 0, 0, 0.7, 0.7]
                tt = np.unique(np.concatenate([np.linspace(0, 1e-9, 150 + 37 * index), bp_t]))
                return Waveform(tt, np.interp(tt, bp_t, bp_v), "CLK", "time")
            return Waveform(t, np.sin(t * 1e10 + index) * 0.35 + 0.35, name, "time")
    v.plot_output(H(), "CLK")
    v.plot_output(H(), "Q")
    for _ in range(20):
        app.processEvents()
    clk, q = v.strips
    assert [c.label for c in clk.curves] == ["CLK (all 3 points)"] and not clk.groups
    assert len(q.curves) == 3 and list(q.groups) == ["Q"]
    assert [lab.text for _, lab in q.legend.items] == ["Q  \u25be 3"]                 # one legend row
    sample, label = q.legend.items[0]
    assert q.group_at(label.sceneBoundingRect().center()) == "Q"
    lst = v.group_menu(q, "Q", show=False)
    assert lst.count() == 3 and lst.item(1).text() == "Nominal tdata=1p"
    lst.item(1).setCheckState(Qt.Unchecked)                                         # hide one point
    assert [c.visible for c in q.curves] == [True, False, True]
    lst.item(0).setCheckState(Qt.Unchecked)
    lst.item(2).setCheckState(Qt.Unchecked)                                         # the last one stays
    assert sum(c.visible for c in q.curves) == 1 and q in v._packed
    lst.item(1).setCheckState(Qt.Checked)
    moved = v.move_group(q, "Q", clk)                                               # the whole group moves
    assert len(moved) == 3 and len(v.strips) == 1 and list(clk.groups) == ["Q"]
    assert len(clk.legend.items) == 2                                               # CLK + the Q group row
    v.close()
