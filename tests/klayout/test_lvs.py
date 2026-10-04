# LVS of user cells: layouts against xschem-style netlists (N FinFET elements, ground 0, .GLOBAL),
# matching cases and seeded errors - wrong fin count, VT, bulk, an open, a short, swapped pins on a
# placed standard cell; fingers; a transistor PCell. KLayout batch mode:
#   klayout -b -r tests/klayout/test_lvs.py
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl.pcells import LIBRARY, register_library  # noqa: E402

DECK = HOME / "pdk/asap7/klayout/lvs/asap7.lvs"
STD = Path(os.environ.get("ASAP7_STDCELLS", HOME.parent / "pdk/asap7/asap7sc7p5t_28"))
TMP = Path(tempfile.mkdtemp())
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


lib = pya.Layout()
lib.read(str(STD / "GDS" / "asap7sc7p5t_28_R_220121a.gds"))


def flat_copy(ly, name, src_name):
    """the library cell's shapes in a new top cell of our own"""
    c = ly.create_cell(name)
    src = lib.cell(src_name)
    for li in lib.layer_indexes():
        c.shapes(ly.layer(lib.get_info(li))).insert(src.shapes(li))
    return c


def lvs(ly, top, spice, *extra):
    gds = TMP / f"{top}.gds"
    ly.write(str(gds))
    sp = TMP / f"{top}.spice"
    sp.write_text(spice)
    res = subprocess.run(["klayout", "-b", "-r", str(DECK), "-rd", f"input={gds}", "-rd", f"topcell={top}",
                          "-rd", f"schematic={sp}", "-rd", f"report={TMP / (top + '.lvsdb')}", *extra],
                         capture_output=True, text=True)
    out = res.stdout + res.stderr
    m = re.search(r"^RESULT LVS \S+ (\w+) circuits=(\d+) bulk=(\d+)", out, re.M)
    return (m.group(1) if m else "error"), out


def layout(name, src="INVx1_ASAP7_75t_R"):
    ly = pya.Layout()
    ly.dbu = lib.dbu
    return ly, flat_copy(ly, name, src)


INV = """.subckt inv A Y
*.PININFO A:I Y:O
NM1 Y A 0 0 nmos_rvt l=20n nfin=3 nf=1 m=1
NM2 Y A VDD VDD pmos_rvt l=20n nfin=3 nf=1 m=1
.ends
.GLOBAL VDD
"""

ly, c = layout("inv")
r, out = lvs(ly, "inv", INV)
check("INVx1's layout matches an inverter schematic (3-fin devices, ground 0 = VSS, global VDD)", r == "match", out[-300:])

r, out = lvs(ly, "inv", INV.replace("nfin=3 nf=1 m=1\nNM2", "nfin=2 nf=1 m=1\nNM2"))
check("a different fin count is a mismatch, reported in fins", r == "mismatch" and "3.0 fins" in out, out[-400:])
r, out = lvs(ly, "inv", INV.replace("pmos_rvt", "pmos_lvt"))
check("a different VT flavour is a mismatch", r == "mismatch", out[-300:])
r, out = lvs(ly, "inv", INV.replace("Y A VDD VDD pmos", "Y A VDD 0 pmos"))
check("a pMOS bulk not on VDD is reported", r == "mismatch" and "bulk on" in out, out[-300:])

# an open: the nMOS drain's V0 to the output removed
ly, c = layout("inv")
v0 = ly.layer(18, 0)
for s in list(c.shapes(v0).each()):
    if s.dbbox().center() == pya.DPoint(0.108, 0.036):
        c.shapes(v0).erase(s)
r, out = lvs(ly, "inv", INV)
check("an open (missing V0) is a mismatch", r == "mismatch", out[-300:])

# a short: M1 joining input and output
ly, c = layout("inv")
c.shapes(ly.layer(19, 0)).insert(pya.DBox(0.03, 0.15, 0.14, 0.168))
r, out = lvs(ly, "inv", INV)
check("a short (M1 between A and Y) is a mismatch", r == "mismatch", out[-300:])

# fingers: INVx2 is two 3-fin fingers per device; the schematic says nfin=3 nf=2
ly, c = layout("inv2", "INVx2_ASAP7_75t_R")
r, out = lvs(ly, "inv2", INV.replace("inv A Y", "inv2 A Y").replace("nf=1", "nf=2"))
check("two fingers combine: nfin=3 nf=2 matches INVx2", r == "match", out[-300:])

# a placed standard cell (black box), wired at the top by labels
ly = pya.Layout()
ly.dbu = lib.dbu
top = ly.create_cell("top2")
inv = ly.create_cell("INVx1_ASAP7_75t_R")
inv.copy_tree(lib.cell("INVx1_ASAP7_75t_R"))
top.insert(pya.CellInstArray(inv.cell_index(), pya.Trans()))
for name, x, y in (("IN", 0.027, 0.15), ("OUT", 0.135, 0.15), ("VDD", 0.1, 0.27), ("VSS", 0.1, 0.0)):
    top.shapes(ly.layer(19, 251)).insert(pya.DText(name, pya.DTrans(x, y)))
TOP = ".subckt top2 IN OUT\nXU1 IN VDD 0 OUT INVx1_ASAP7_75t_R\n.ends\n.GLOBAL VDD\n"
r, out = lvs(ly, "top2", TOP)
check("a placed library cell matches its instance (pins by name, the CDL's pin order)", r == "match", out[-300:])
r, out = lvs(ly, "top2", TOP.replace("XU1 IN VDD 0 OUT", "XU1 OUT VDD 0 IN"))
check("swapped pins on the placed cell are a mismatch (net names)", r == "mismatch" and "LVS net name" in out,
      out[-300:])
r, out = lvs(ly, "top2", TOP, "-rd", "stdcells=check")
check("stdcells=check compares the placed cell's transistors too (and they match)", r == "match", out[-300:])

# a transistor PCell, 3 fins x 2 fingers, not wired (no gate contact either): two 3-fin fingers
# sharing the middle diffusion (fins counted from the drawn ACTIVE)
register_library()
ly = pya.Layout()
ly.dbu = 0.00025
ly.technology_name = "asap7"
top = ly.create_cell("t1")
pc = ly.create_cell("nmos", LIBRARY, {"nfin": 3, "nf": 2})
top.insert(pya.CellInstArray(pc.cell_index(), pya.Trans()))
flat = ly.create_cell("t1f")             # flattened: no pins between hierarchy levels to worry about
flat.copy_tree(top)
flat.flatten(True)
r, out = lvs(ly, "t1f", ".subckt t1f\nNM1 d g1 s1 0 nmos_rvt l=20n nfin=3 nf=1\n"
                         "NM2 d g2 s2 0 nmos_rvt l=20n nfin=3 nf=1\n.ends\n")
check("the nMOS PCell (nfin=3, nf=2) extracts as two 3-fin nmos_rvt fingers", r == "match", out[-400:])

print("PASS lvs" if not failures else f"FAIL lvs: {', '.join(failures)}")
