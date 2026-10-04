# OpenLayout > Run LVS in KLayout (with a main window, headless): a workarea cell with an xschem
# schematic and a layout, matched; an edit that breaks it; a batch run's results in the netlist
# browser.
#   klayout -e -z -nc -r tests/klayout/test_lvs_gui.py
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path[:0] = [str(HOME / "klayout" / "python"), str(HOME / "python")]

import pya  # noqa: E402

from openlayout.workarea import Workarea  # noqa: E402
from openlayout_kl import gui, lvs  # noqa: E402

STD = Path(os.environ.get("ASAP7_STDCELLS", HOME.parent / "pdk/asap7/asap7sc7p5t_28"))
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)
check("Run LVS is in the OpenLayout menu", mw.menu().is_valid("openlayout_menu.run_lvs"))

# the cell: an inverter schematic (3-fin devices, output Y) and the INVx1 geometry as its layout
wa = Workarea.create(Path(tempfile.mkdtemp()) / "wa", "cpu8")
cell_dir = wa.library("cpu8").path / "inv"
cell_dir.mkdir()
sch = (HOME / "tests/klayout/inv_globals.sch").read_text().replace("lab=Z", "lab=Y").replace("nfin=2", "nfin=3")
(cell_dir / "inv.sch").write_text(sch)
lib = pya.Layout()
lib.read(str(STD / "GDS" / "asap7sc7p5t_28_R_220121a.gds"))
ly = pya.Layout()
ly.dbu = lib.dbu
c = ly.create_cell("inv")
for li in lib.layer_indexes():
    c.shapes(ly.layer(lib.get_info(li))).insert(lib.cell("INVx1_ASAP7_75t_R").shapes(li))
gds = cell_dir / "inv.gds"
ly.write(str(gds))

mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
res = lvs.run_current(mw)
check("Run LVS: the layout matches its xschem schematic; results in the netlist browser",
      res is not None and res["match"] and view.num_l2ndbs() >= 1, (res, view.num_l2ndbs()))

# remove the output's nMOS contact in the editor (unsaved): the next run sees it
cv = view.active_cellview()
v0 = cv.layout().layer(18, 0)
top = cv.layout().cell("inv")
for s in list(top.shapes(v0).each()):
    if s.dbbox().center() == pya.DPoint(0.108, 0.036):
        top.shapes(v0).erase(s)
res = lvs.run_current(mw)
check("after an edit that opens the output, Run LVS reports the mismatch", res is not None and not res["match"]
      and res["circuits"] >= 1, res)

# batch (the hub's LVS button): `openlayout lvs` finds inv.sch next to the layout
report = Path(tempfile.mkdtemp()) / "inv.lvsdb"
out = subprocess.run(["openlayout", "lvs", str(gds), "--cell", "inv", "--report", str(report)],
                     capture_output=True, text=True)
check("openlayout lvs netlists the schematic next to the layout and matches", "RESULT LVS inv match" in out.stdout
      and "inv.sch" in out.stdout, (out.stdout + out.stderr)[-400:])
before = mw.current_view().num_l2ndbs()
check("its results open in the netlist browser", lvs.show_results(str(gds), "inv", str(report), mw)
      and mw.current_view().num_l2ndbs() == before + 1)

# a library cell without a schematic: against its CDL
lib_gds = STD / "GDS" / "asap7sc7p5t_28_R_220121a.gds"
out = subprocess.run(["openlayout", "lvs", str(lib_gds), "--cell", "NAND2xp33_ASAP7_75t_R",
                      "--report", str(Path(tempfile.mkdtemp()) / "n.lvsdb")], capture_output=True, text=True)
check("a library cell without a schematic is checked against the CDL", "RESULT LVS NAND2xp33_ASAP7_75t_R match"
      in out.stdout and "standard-cell CDL" in out.stdout, (out.stdout + out.stderr)[-300:])

print("PASS lvs_gui" if not failures else f"FAIL lvs_gui: {', '.join(failures)}")
