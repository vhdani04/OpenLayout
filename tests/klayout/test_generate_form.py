# The Generate Layout form (pins and their layers, the frame), run in KLayout with a main window
# (headless):
#   klayout -e -z -nc -r tests/klayout/test_generate_form.py
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
wa = Workarea.create(Path(tempfile.mkdtemp()) / "wa", "cpu8")
lib = wa.library("cpu8")
for name in ("inv", "inv2"):
    (lib.path / name).mkdir()
    shutil.copy(HOME / "tests/klayout/inv_globals.sch", lib.path / name / f"{name}.sch")   # ports A, Z; VDD, VSS

info = gen.read_schematic(lib.path / "inv" / "inv.sch")
table = gen.pin_table(info)
check("the form lists the ports, then the supplies", [(p["name"], p["supply"]) for p in table["pins"]]
      == [("A", False), ("Z", False), ("VDD", True), ("VSS", True)] and not table["frame"] and table["has_mos"],
      table)


def run_form(edit=None):
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
    return generate_form.ask_generate(mw, "inv", table)


answer = run_form()
check("defaults: the ports on M1; VDD / VSS are left to the frame's rails; the frame is created",
      answer == {"pins": {"A": "m1", "Z": "m1"}, "frame": True}, answer)


def edit(d):
    grid = [c for c in d.children() if type(c).__name__.startswith("QTableWidget")][0]
    grid.item(0, generate_form.COL_CREATE).setCheckState(pya.Qt.Unchecked)       # no A
    grid.cellWidget(1, generate_form.COL_LAYER).currentIndex = 1                  # Z on M2
    grid.item(3, generate_form.COL_CREATE).setCheckState(pya.Qt.Checked)         # VSS too ...
    grid.cellWidget(3, generate_form.COL_LAYER).currentIndex = 2                  # ... on M3


answer = run_form(edit)
check("the form returns the chosen pins and layers", answer == {"pins": {"Z": "m2", "VSS": "m3"}, "frame": True},
      answer)

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
