# Schematic-driven layout + connectivity check, run in KLayout batch mode:
#   klayout -b -r tests/klayout/test_layoutxl.py
# Prints one PASS/FAIL line per check and a final PASS/FAIL summary.
import os
import shutil
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path[:0] = [str(HOME / "klayout" / "python"), str(HOME / "python")]

import pya  # noqa: E402

from openlayout.workarea import Workarea  # noqa: E402
from openlayout_kl import connectivity, generate  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


wa = Workarea.create(Path(tempfile.mkdtemp()) / "wa", "cpu8")
lib = wa.library("cpu8")
(lib.path / "inv").mkdir()
shutil.copy(HOME / "tests/klayout/inv_pins.sch", lib.path / "inv" / "inv.sch")
sch = lib.path / "inv" / "inv.sch"

# 1. generate from source
rep = generate.generate(sch)
check("generate adds devices", sorted(rep["added"]) == ["M1", "M2"], rep["added"])
check("generate adds pins", sorted(rep["pins_added"]) == ["A", "VDD", "VSS", "Y"], rep["pins_added"])
gds = lib.path / "inv" / "inv.gds"
check("layout and link written", gds.is_file() and connectivity.conn_file(gds).is_file())

# 2. links survive GDS round trip
ly = pya.Layout()
ly.technology_name = "asap7"
ly.read(str(gds))
top = ly.cell("inv")
names = {connectivity.instance_name(i): i for i in top.each_inst()}
check("instance names persisted in GDS", set(names) == {"M1", "M2"}, sorted(n for n in names if n))
check("PCell parameters from schematic", names["M1"].pcell_parameters_by_name()["nf"] == 2
      and names["M2"].pcell_parameters_by_name()["nfin"] == 2)

# 3. everything open at first
conn = connectivity.load_conn(gds)
res = connectivity.check(ly, top, conn)
pieces = {n: v["pieces"] for n, v in res["nets"].items()}
check("all nets open after generation", pieces == {"A": 3, "Y": 3, "VDD": 3, "VSS": 3}, pieces)
check("flight lines per open net", all(len(v["lines"]) == v["pieces"] - 1 for v in res["nets"].values()))

# 4. route net A: LIG between the two gate straps, V0 + M1 over to pin A
ga = [t for t in connectivity.terminals(ly, top, conn)[0] if t.net == "A"]
gates = [t.point for t in ga if t.term == "g"]
pin = [t.point for t in ga if t.owner is None][0]
lig, v0, m1 = (ly.layer(n, 0) for n in (16, 18, 19))
x = gates[0].x
top.shapes(lig).insert(pya.DPath([pya.DPoint(gates[0].x, gates[0].y), pya.DPoint(x, gates[1].y),
                                  pya.DPoint(gates[1].x, gates[1].y)], 0.016, 0.011, 0.011))
top.shapes(v0).insert(pya.DBox(x - 0.009, gates[0].y - 0.009, x + 0.009, gates[0].y + 0.009))
top.shapes(m1).insert(pya.DPath([pya.DPoint(x, gates[0].y), pya.DPoint(x, pin.y),
                                 pya.DPoint(pin.x, pin.y)], 0.018, 0.009, 0.009))
res = connectivity.check(ly, top, conn)
check("routed net A is complete", res["nets"]["A"]["pieces"] == 1, res["nets"]["A"]["unconnected"])
check("other nets still open", res["nets"]["Y"]["pieces"] == 3)

# 5. short A to Y with an M1 bar between the two pins
yp = [t.point for t in connectivity.terminals(ly, top, conn)[0] if t.owner is None and t.net == "Y"][0]
top.shapes(m1).insert(pya.DBox(pin.x - 0.01, min(pin.y, yp.y), pin.x + 0.01, max(pin.y, yp.y)))
res = connectivity.check(ly, top, conn)
check("short detected", "Y" in res["nets"]["A"]["shorts"] and "A" in res["nets"]["Y"]["shorts"],
      res["nets"]["A"]["shorts"])

# 6. update from source: change M1 to nf=3 and add a device
text = sch.read_text().replace("name=M1 l=20n nfin=3 nf=2", "name=M1 l=20n nfin=3 nf=3")
text += "C {asap7_devices/nmos_rvt/nmos_rvt.sym} 0 300 0 0 {name=M3 l=20n nfin=1 nf=1 m=1}\n"
sch.write_text(text)
rep = generate.generate(sch)
check("update changes parameters", rep["updated"] == ["M1"], rep)
check("update adds new device", rep["added"] == ["M3"], rep["added"])
ly2 = pya.Layout()
ly2.technology_name = "asap7"
ly2.read(str(gds))
n2 = {connectivity.instance_name(i): i for i in ly2.cell("inv").each_inst()}
check("update keeps existing instances", n2["M1"].pcell_parameters_by_name()["nf"] == 3 and "M3" in n2)

# 7. standard cells from the ASAP7 libraries
(lib.path / "chain").mkdir()
shutil.copy(HOME / "tests/xschem/tb_stdcells/tb_stdcells.sch", lib.path / "chain" / "chain.sch")
rep = generate.generate(lib.path / "chain" / "chain.sch")
check("std cells placed", sorted(rep["added"]) == ["U1", "U2", "U3"], rep)
ly3 = pya.Layout()
ly3.technology_name = "asap7"
ly3.read(str(lib.path / "chain" / "chain.gds"))
conn3 = connectivity.load_conn(lib.path / "chain" / "chain.gds")
res3 = connectivity.check(ly3, ly3.cell("chain"), conn3)
check("std-cell pins found", res3["nets"].get("n1", {}).get("terminals") == 2, res3["nets"].get("n1"))
check("n1 open between NAND2 and INV", res3["nets"]["n1"]["pieces"] == 2)
check("no false shorts through std cells", not any(v["shorts"] for v in res3["nets"].values()),
      {n: v["shorts"] for n, v in res3["nets"].items() if v["shorts"]})

print("PASS layoutxl" if not failures else f"FAIL layoutxl: {', '.join(failures)}")
