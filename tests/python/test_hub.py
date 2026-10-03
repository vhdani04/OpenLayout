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

from openlayout.workarea import SCHEMATIC, Workarea  # noqa: E402


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
