# OpenLayout > Run DRC in KLayout (with a main window, headless), and a batch run's results shown
# in the marker browser:
#   klayout -e -z -nc -r tests/klayout/test_drc_gui.py
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path[:0] = [str(HOME / "klayout" / "python"), str(HOME / "python")]

import pya  # noqa: E402

from openlayout_kl import drc, gui  # noqa: E402
from openlayout_kl.asap7 import LAYERS  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)
check("Run DRC is in the OpenLayout menu", mw.menu().is_valid("openlayout_menu.run_drc"))

# a layout with two M1 wires 10 nm apart (M1.S.1) and one with a 16 nm wire (M1.W.1)
tmp = Path(tempfile.mkdtemp())
ly = pya.Layout()
ly.dbu = 0.00025
top = ly.create_cell("BAD")
m1 = ly.layer(LAYERS["m1"], 0)
top.shapes(m1).insert(pya.DBox(0, 0, 0.018, 0.2))
top.shapes(m1).insert(pya.DBox(0.028, 0, 0.046, 0.2))
top.shapes(m1).insert(pya.DBox(0.5, 0, 0.516, 0.2))
gds = tmp / "bad.gds"
ly.write(str(gds))

mw.load_layout(str(gds), "asap7", 1)
rdb = drc.run_current(mw)
view = mw.current_view()
rules = {rdb.category_by_id(i.category_id()).name() for i in rdb.each_item()} if rdb else set()
check("Run DRC checks the current cell and its results are in the view's marker browser",
      rdb is not None and view.num_rdbs() >= 1 and {"M1.S.1", "M1.W.1"} <= rules, sorted(rules))

# fix the layout in the editor (unsaved): the next run sees the edited layout
cv = view.active_cellview()
cv.layout().cell("BAD").shapes(cv.layout().layer(LAYERS["m1"], 0)).clear()
cv.layout().cell("BAD").shapes(cv.layout().layer(LAYERS["m1"], 0)).insert(pya.DBox(0, 0, 0.018, 0.2))
rdb = drc.run_current(mw)
check("a run after editing checks the edited layout (clean now)", rdb is not None and rdb.num_items() == 0,
      rdb.num_items() if rdb else None)

# a batch run (as the hub's DRC button does), shown on the open layout
report = tmp / "bad.drc.lyrdb"
res = subprocess.run(["openlayout", "drc", str(gds), "--cell", "BAD", "--report", str(report)],
                     capture_output=True, text=True)
check("openlayout drc runs and summarises per rule", res.returncode == 0 and "M1.S.1" in res.stdout
      and "RESULT DRC BAD violations=" in res.stdout, (res.stdout + res.stderr)[-300:])
n = drc.show_results(str(gds), "BAD", str(report), mw)
check("its results open in the marker browser of that layout's view", n >= 2
      and mw.current_view().num_rdbs() >= 3, (n, mw.current_view().num_rdbs()))

print("PASS drc_gui" if not failures else f"FAIL drc_gui: {', '.join(failures)}")
