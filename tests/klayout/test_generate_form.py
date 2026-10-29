# The Generate Layout form (pins and their layers, the frame), run in KLayout with a main window
# (headless):
#   klayout -e -z -nc -r tests/klayout/test_generate_form.py
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path[:0] = [str(HOME / "klayout" / "python"), str(HOME / "python")]

import pya  # noqa: E402

from openlayout.workarea import Workarea  # noqa: E402
from openlayout_kl import generate as gen  # noqa: E402
from openlayout_kl import generate_form, gui  # noqa: E402
from openlayout_kl.asap7 import LAYERS  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)
wa = Workarea.create(Path(tempfile.mkdtemp()) / "wa", "testlib")
lib = wa.library("testlib")
for name in ("inv", "inv2", "inv3"):
    (lib.path / name).mkdir()
    shutil.copy(HOME / "tests/klayout/inv_globals.sch", lib.path / name / f"{name}.sch")   # ports A, Z; VDD, VSS

info = gen.read_schematic(lib.path / "inv" / "inv.sch")
table = gen.pin_table(info)
check("the form lists the ports, then the supplies", [(p["name"], p["supply"]) for p in table["pins"]]
      == [("A", False), ("Z", False), ("VDD", True), ("VSS", True)] and not table["frame"] and table["has_mos"],
      table)
check("the form lists the instances by kind", [(i["name"], i["type"], i["exists"]) for i in table["instances"]]
      == [("M1", "nmos_rvt nfin=2 nf=1", False), ("M2", "pmos_rvt nfin=2 nf=1", False)], table["instances"])


def find(widget, name):
    """the descendant widget with this objectName"""
    for c in widget.children():
        if getattr(c, "objectName", None) == name:
            return c
        hit = find(c, name) if hasattr(c, "children") else None
        if hit is not None:
            return hit
    return None


def run_form(edit=None, t=None):
    """open the real form; a timer edits it (optional) and presses Generate"""
    timer = pya.QTimer(mw)
    timer.interval = 300
    timer.singleShot = True

    def act():
        d = pya.QApplication.activeModalWidget()
        if d is None:
            return
        if edit:
            edit(d)
        d.accept()
    timer.timeout = act
    timer.start()
    return generate_form.ask_generate(mw, "inv", t or table)


answer = run_form()
check("defaults: the ports on M1; VDD / VSS are left to the frame's rails; the frame is created",
      answer == {"pins": {"A": "m1", "Z": "m1"}, "frame": True, "instances": None}, answer)


def edit(d):
    grid = find(d, "pins")
    grid.item(0, generate_form.COL_CREATE).setCheckState(pya.Qt.Unchecked)       # no A
    grid.cellWidget(1, generate_form.COL_LAYER).currentIndex = 1                  # Z on M2
    grid.item(3, generate_form.COL_CREATE).setCheckState(pya.Qt.Checked)         # VSS too ...
    grid.cellWidget(3, generate_form.COL_LAYER).currentIndex = 2                  # ... on M3


answer = run_form(edit)
check("the form returns the chosen pins and layers",
      answer == {"pins": {"Z": "m2", "VSS": "m3"}, "frame": True, "instances": None}, answer)

# ---- an array: instances grouped by kind, a picker per kind, Select All / Deselect All -----------
array = {"pins": [{"name": f"P[{i}]", "dir": "O", "supply": False, "exists": False} for i in range(96)],
         "instances": [{"name": f"x{i + 1}", "type": "b2SRAMsbc", "exists": i < 4} for i in range(32)]
         + [{"name": "M1", "type": "nmos_rvt nfin=2 nf=1", "exists": False}],
         "frame": True, "has_mos": False}
seen = {}


def look(d):
    g = find(d, "instances")
    seen["rows"] = [(g.item(r, 1).text, g.item(r, 2).text, g.item(r, 3).text) for r in range(g.rowCount)]
    seen["tabs"] = [find(d, "tabs").tabText(i) for i in range(find(d, "tabs").count)]


answer = run_form(look, array)
check("Instances tab: one row per kind with its count", seen.get("rows") == [
    ("b2SRAMsbc", "x32", "4 exist"), ("nmos_rvt nfin=2 nf=1", "x1", "")], seen)
check("the tabs are Instances, then Pins", seen.get("tabs") == ["Instances (33)", "Pins (96)"], seen)
check("by default every instance and every new pin", answer["instances"] is None and len(answer["pins"]) == 96,
      answer["instances"])


def deselect_pins(d):
    pins_tab = find(d, "tabs").widget(1)
    find(pins_tab, "deselect_all").click()
    find(pins_tab, "pins").item(5, generate_form.COL_CREATE).setCheckState(pya.Qt.Checked)


answer = run_form(deselect_pins, array)
check("Pins tab: Deselect All, then one pin", answer["pins"] == {"P[5]": "m1"}, answer["pins"])


def untick_kind(d):
    find(d, "instances").item(0, generate_form.COL_PLACE).setCheckState(pya.Qt.Unchecked)


answer = run_form(untick_kind, array)
check("unticking a kind leaves out all of its instances", answer["instances"] == {"M1"}, answer["instances"])


def instances_none_then_all(d):
    page = find(d, "tabs").widget(0)
    find(page, "deselect_all").click()
    g = find(d, "instances")
    seen["none"] = [g.item(r, 0).checkState == pya.Qt.Unchecked for r in range(g.rowCount)]
    find(page, "select_all").click()


answer = run_form(instances_none_then_all, array)
check("Instances tab: Deselect All / Select All", seen.get("none") == [True, True] and answer["instances"] is None,
      (seen.get("none"), answer["instances"]))


def pick_some(d):
    """double-click the b2SRAMsbc row; in its window, Deselect All, tick x3 and x7, OK"""
    picker = pya.QTimer(mw)
    picker.interval = 200
    picker.singleShot = True

    def in_picker():
        p = pya.QApplication.activeModalWidget()
        m = find(p, "members")
        seen["members"] = [(m.item(r, 1).text, m.item(r, 2).text) for r in range(m.rowCount)][:5]
        seen["picker_title"] = p.windowTitle
        find(p, "deselect_all").click()
        m.item(2, 0).setCheckState(pya.Qt.Checked)
        m.item(6, 0).setCheckState(pya.Qt.Checked)
        p.accept()
    picker.timeout = in_picker
    picker.start()
    seen["picker_timer"] = picker
    g = find(d, "instances")
    g.emit_cellDoubleClicked(0, 1)                 # the picker runs (modal) inside this call
    seen["row_state"] = g.item(0, 0).checkState


answer = run_form(pick_some, array)
check("double-click opens the instances of that kind", seen.get("picker_title") == "b2SRAMsbc x32"
      and seen.get("members") == [("x1", "exists"), ("x2", "exists"), ("x3", "exists"), ("x4", "exists"),
                                   ("x5", "")], (seen.get("picker_title"), seen.get("members")))
check("picking some shows a partial tick and returns just those", seen.get("row_state") == pya.Qt.PartiallyChecked
      and answer["instances"] == {"x3", "x7", "M1"}, (seen.get("row_state"), answer["instances"]))

# generating with chosen layers: pins on those metals' pin purpose, minimum-width squares
real = generate_form.ask_generate
generate_form.ask_generate = lambda parent, cell, t: {"pins": {"A": "m2", "Z": "m3"}, "frame": True}
try:
    rep = gui.instance.generate_for(lib.path / "inv" / "inv.sch", ask=True)
finally:
    generate_form.ask_generate = real
check("generate makes exactly the chosen pins", sorted(rep["pins_added"]) == ["A", "Z"], rep["pins_added"])
ly = pya.Layout()
ly.technology_name = "asap7"
ly.read(str(lib.path / "inv" / "inv.gds"))
top = ly.cell("inv")


def pins_on(metal):
    li = ly.find_layer(LAYERS[metal], 251)
    if li is None:
        return {}
    texts = {s.text_string for s in top.shapes(li).each(pya.Shapes.STexts)}
    boxes = [s.dbbox() for s in top.shapes(li).each(pya.Shapes.SBoxes)]
    return {"texts": texts, "sizes": sorted({(round(b.width(), 4), round(b.height(), 4)) for b in boxes})}


check("A is an 18 nm M2 pin, Z an 18 nm M3 pin", pins_on("m2") == {"texts": {"A"}, "sizes": [(0.018, 0.018)]}
      and pins_on("m3") == {"texts": {"Z"}, "sizes": [(0.018, 0.018)]}
      and "A" not in pins_on("m1").get("texts", set()), (pins_on("m1"), pins_on("m2"), pins_on("m3")))
check("the frame was created", ly.find_layer(LAYERS["boundary"], 0) is not None
      and not top.shapes(ly.find_layer(LAYERS["boundary"], 0)).is_empty())

# instances left out are not placed (but stay in the schematic link)
generate_form.ask_generate = lambda parent, cell, t: {"pins": {}, "frame": True, "instances": {"M2"}}
try:
    rep = gui.instance.generate_for(lib.path / "inv3" / "inv3.sch", ask=True)
finally:
    generate_form.ask_generate = real
ly3 = pya.Layout()
ly3.technology_name = "asap7"
ly3.read(str(lib.path / "inv3" / "inv3.gds"))
names = sorted(gen.instance_name(i) for i in ly3.cell("inv3").each_inst() if gen.instance_name(i))
link = json.loads(gen.conn_file(lib.path / "inv3" / "inv3.gds").read_text())
check("only the chosen instances are placed", names == ["M2"] and rep["left_out"] == ["M1"]
      and sorted(link["instances"]) == ["M1", "M2"], (names, rep["left_out"], sorted(link["instances"])))
check("the status line says how many were left out", "1 left out" in gui.instance.describe(rep), gui.instance.describe(rep))

# the LSW is docked on the left, Select and Connectivity on the right
check("the LSW (layers) is on the left", mw.dockWidgetArea(gui.instance.lsw.dock) == pya.Qt.LeftDockWidgetArea
      and mw.dockWidgetArea(gui.instance.select.dock) == pya.Qt.RightDockWidgetArea
      and mw.dockWidgetArea(gui.instance.nets.dock) == pya.Qt.RightDockWidgetArea)

# without the frame: no boundary
generate_form.ask_generate = lambda parent, cell, t: {"pins": {"A": "m1"}, "frame": False}
try:
    rep = gui.instance.generate_for(lib.path / "inv2" / "inv2.sch", ask=True)
finally:
    generate_form.ask_generate = real
ly2 = pya.Layout()
ly2.technology_name = "asap7"
ly2.read(str(lib.path / "inv2" / "inv2.gds"))
b = ly2.find_layer(LAYERS["boundary"], 0)
check("unchecking the frame creates no frame / boundary", (b is None or ly2.cell("inv2").shapes(b).is_empty())
      and rep["pins_added"] == ["A"], rep["pins_added"])

# cancelling the form generates nothing
generate_form.ask_generate = lambda parent, cell, t: None
try:
    rep = gui.instance.generate_for(lib.path / "inv2" / "inv2.sch", ask=True)
finally:
    generate_form.ask_generate = real
check("cancelling the form generates nothing", rep is None)

print("PASS generate_form" if not failures else f"FAIL generate_form: {', '.join(failures)}")
