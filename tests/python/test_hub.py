"""Hub smoke tests (offscreen Qt): Library Manager contents, CIW commands, netlist + simulate."""
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()  # Qt caches this path: keep the user's hub settings untouched
from PySide6.QtWidgets import QApplication  # noqa: E402

from openlayout.workarea import SCHEMATIC, Workarea, view_type  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path):
    from openlayout.hub.main_window import MainWindow
    wa = Workarea.create(tmp_path / "wa", "cpu8")
    tb = wa.library("cpu8").path / "tb_inv"
    tb.mkdir()
    shutil.copy(Path(os.environ["OPENLAYOUT_HOME"]) / "tests/xschem/tb_inv/tb_inv.sch", tb)
    w = MainWindow(wa)
    yield w
    w.close()


def items(column):
    return [column.list.item(i).text() for i in range(column.list.count())]


def test_library_manager_lists(win):
    assert items(win.lm.libs)[0] == "cpu8"
    assert "asap7sc7p5t_28_R" in items(win.lm.libs)
    win.lm.select("asap7sc7p5t_28_R", "INVx1_ASAP7_75t_R")
    assert items(win.lm.views) == ["symbol", "layout"]
    assert not win.a_rename.isEnabled()  # PDK cells are read-only


def test_cell_filter(win):
    win.lm.select("asap7sc7p5t_28_R")
    win.lm.cells.filter.setText("dffhqn*")
    visible = [win.lm.cells.list.item(i).text() for i in range(win.lm.cells.list.count())
               if not win.lm.cells.list.item(i).isHidden()]
    assert visible and all(v.startswith("DFFHQN") for v in visible)


def test_ciw_commands(win):
    win._run_ciw("ol.new_view('cpu8', 'nand2', 'schematic')")
    assert win.workarea.library("cpu8").cell("nand2").view("schematic")
    win._run_ciw("print(ol.cells('cpu8'))")
    assert "['nand2', 'tb_inv']" in win.ciw.log.toPlainText()
    win._run_ciw("1/0")
    assert "ZeroDivisionError" in win.ciw.log.toPlainText()


def test_simulate_records_state(win, app):
    cell = win.workarea.library("cpu8").cell("tb_inv")
    win.simulate(cell)
    end = time.time() + 60
    while time.time() < end and "sim" not in win.workarea.cell_state(cell):
        app.processEvents()
        time.sleep(0.02)
    state = win.workarea.cell_state(cell)
    assert state["netlist"]["ok"] and state["sim"]["ok"]
    assert state["sim"]["detail"].startswith("PASS")


def wait_state(win, app, cell, step, timeout=120):
    end = time.time() + timeout
    while time.time() < end and step not in win.workarea.cell_state(cell):
        app.processEvents()
        time.sleep(0.02)
    return win.workarea.cell_state(cell).get(step)


def test_drc_records_state(win, app):
    # a library cell: clean; results under verify/, the read-only library untouched
    inv = win.workarea.library("asap7sc7p5t_28_R").cell("INVx1_ASAP7_75t_R")
    win.lm.select("asap7sc7p5t_28_R", "INVx1_ASAP7_75t_R")
    assert win.a_drc.isEnabled()
    win.drc(inv)
    state = wait_state(win, app, inv, "drc")
    assert state and state["ok"] and state["detail"] == "clean"
    assert (win.workarea.verify_dir(inv) / "INVx1_ASAP7_75t_R.drc.lyrdb").is_file()
    # a cell with an M1 width error: not clean, and the results go to KLayout
    import subprocess
    cell = win.workarea.new_view(win.workarea.library("cpu8"), "bad", view_type("layout")).cell
    script = cell.path / "mk.py"
    script.write_text("\n".join([
        "import pya",
        "ly = pya.Layout(); ly.dbu = 0.00025; c = ly.create_cell('bad')",
        "c.shapes(ly.layer(19, 0)).insert(pya.DBox(0, 0, 0.016, 0.2))",
        f"ly.write({str(cell.path / 'bad.gds')!r})", ""]))
    subprocess.run(["klayout", "-b", "-r", str(script)], check=True)
    script.unlink()
    sent = []
    win._in_thread = lambda bridge, fn: sent.append(bridge.name)
    win.drc(cell)
    state = wait_state(win, app, cell, "drc")
    assert state and not state["ok"] and state["detail"].startswith("1 violation")
    assert sent == ["klayout"]
    assert "M1.W.1" in win.ciw.log.toPlainText()


def test_lvs_records_state(win, app):
    # a library cell without a schematic: checked against the CDL
    nand = win.workarea.library("asap7sc7p5t_28_R").cell("NAND2xp33_ASAP7_75t_R")
    win.lm.select("asap7sc7p5t_28_R", "NAND2xp33_ASAP7_75t_R")
    assert win.a_lvs.isEnabled()
    win.lvs(nand)
    state = wait_state(win, app, nand, "lvs")
    assert state and state["ok"] and state["detail"] == "match"
    assert (win.workarea.verify_dir(nand) / "NAND2xp33_ASAP7_75t_R.lvsdb").is_file()
    assert "layout matches the schematic" in win.ciw.log.toPlainText()


def test_pex_records_state(win, app):
    nand = win.workarea.library("asap7sc7p5t_28_R").cell("NAND2xp33_ASAP7_75t_R")
    win.lm.select("asap7sc7p5t_28_R", "NAND2xp33_ASAP7_75t_R")
    assert win.a_pex.isEnabled()
    win.pex(nand)
    state = wait_state(win, app, nand, "pex")
    assert state and state["ok"] and state["detail"].startswith("4 transistors")
    out = win.workarea.verify_dir(nand) / "NAND2xp33_ASAP7_75t_R.pex.spice"
    assert out.is_file() and ".subckt NAND2xp33_ASAP7_75t_R A B VDD VSS Y" in out.read_text()
    assert "total capacitance" in win.ciw.log.toPlainText()


def test_command_server(win, app):
    """What the xschem/KLayout OpenLayout menus do: openlayout hubcmd -> hub over localhost."""
    import threading
    from openlayout import cli
    port = win.workarea.session()["hub_port"]
    assert cli.hub_port(str(win.workarea.root / "libraries" / "cpu8" / "tb_inv" / "tb_inv.sch")) == port

    def call(req):
        out = []
        t = threading.Thread(target=lambda: out.append(cli.send(port, req)), daemon=True)
        t.start()
        end = time.time() + 10
        while t.is_alive() and time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        return out[0]

    assert call({"cmd": "ping"})["ok"]
    sch = str(win.workarea.library("cpu8").path / "tb_inv" / "tb_inv.sch")
    reply = call({"cmd": "select", "path": sch})
    assert reply["ok"] and win.lm.current_cell().key == "cpu8/tb_inv"
    reply = call({"cmd": "open", "path": sch, "view": "layout"})
    assert not reply["ok"] and "no layout view" in reply["error"]
    assert not call({"cmd": "select", "path": "/tmp/not/in/workarea.sch"})["ok"]


def test_session_cleared_on_close(win):
    session = win.workarea.session_file
    assert session.is_file()
    win.close()
    assert not session.exists()


def test_new_cell_view_rejects_readonly(win):
    from openlayout.workarea import WorkareaError
    with pytest.raises(WorkareaError):
        win.workarea.new_view(win.workarea.library("asap7_devices"), "x", SCHEMATIC)
