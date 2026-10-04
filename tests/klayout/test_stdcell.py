# Standard-cell frame, row-mode FinFETs and chaining, run in KLayout batch mode:
#   klayout -b -r tests/klayout/test_stdcell.py
# The geometry is checked against the ASAP7 library cells themselves: an inverter and a NAND2 built
# from the frame + PCells must match INVx1 / NAND2xp33 on every front-end layer.
import os
import sys
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import chain  # noqa: E402
from openlayout_kl.asap7 import LAYERS  # noqa: E402
from openlayout_kl.pcells import LIBRARY, register_library  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


register_library()
GDS = Path(os.environ.get("ASAP7_STDCELLS", HOME.parent / "pdk/asap7/asap7sc7p5t_28")) / "GDS"
lib = pya.Layout()
lib.read(str(GDS / "asap7sc7p5t_28_R_220121a.gds"))

ly = pya.Layout()
ly.dbu = 0.00025
ly.technology_name = "asap7"
FRONT = ["well", "fin", "gate", "gcut", "active", "nselect", "pselect", "sdt", "boundary"]


def place(cell, name, x_nm, **params):
    pc = ly.create_cell(name, LIBRARY, params)
    return cell.insert(pya.DCellInstArray(pc.cell_index(), pya.DTrans(x_nm / 1000, 0)))


def region(layout, cell, layer):
    li = layout.find_layer(LAYERS[layer], 0)
    return pya.Region() if li is None else pya.Region(cell.begin_shapes_rec(li)).merged()


def compare(cell, ref_name):
    ref = lib.cell(ref_name)
    bad = {}
    for layer in FRONT:
        a = region(ly, cell, layer)
        b = region(lib, ref, layer)
        # the library's gates end at 275 or 275.5 nm: compare within half a nanometre
        x = (a ^ b).sized(-1)
        if not x.is_empty():
            bad[layer] = str(x)[:120]
    return bad


# INVx1: frame of 3 gate pitches, a 3-fin nMOS and pMOS in the same column (one gate through both)
inv = ly.create_cell("INV")
place(inv, "stdcell", 0, cpp=3)
place(inv, "nmos", 0, row=True, nfin=3, nf=1)
place(inv, "pmos", 0, row=True, nfin=3, nf=1)
bad = compare(inv, "INVx1_ASAP7_75t_R")
check("frame + row devices reproduce INVx1 (front-end layers)", not bad, bad)

# NAND2xp33: two 2-fin nMOS chained in series (no contact on the inner node), a 1-fin pMOS with
# two fingers in parallel
nand = ly.create_cell("NAND")
place(nand, "stdcell", 0, cpp=4)
place(nand, "nmos", 0, row=True, nfin=2, nf=1, abut_right=True, contact_right=False)
place(nand, "nmos", 54, row=True, nfin=2, nf=1, abut_left=True, contact_left=False)
place(nand, "pmos", 0, row=True, nfin=1, nf=2)
bad = compare(nand, "NAND2xp33_ASAP7_75t_R")
check("chained series nMOS reproduce NAND2xp33 (front-end layers)", not bad, bad)

check("the comparison notices differences", bool(compare(inv, "NAND2xp33_ASAP7_75t_R")))

# chaining: standalone 2-fin nMOS, nets from a schematic link (s/d per instance)
conn = {"instances": {
    "MA": {"kind": "mos", "type": "nmos", "terminals": {"s": "VSS", "d": "X", "g": "A"}},
    "MB": {"kind": "mos", "type": "nmos", "terminals": {"s": "X", "d": "Y", "g": "B"}},
    "MC": {"kind": "mos", "type": "nmos", "terminals": {"s": "Z", "d": "X", "g": "C"}},
    "MD": {"kind": "mos", "type": "nmos", "terminals": {"s": "P", "d": "Q", "g": "D"}},
    "ME": {"kind": "mos", "type": "nmos", "terminals": {"s": "Y", "d": "W", "g": "E"}},
}}


def device(cell, name, x_nm, mirrored=False):
    inst = place(cell, "nmos", 0, nfin=2, nf=1)
    inst.trans = pya.Trans(pya.Trans.M90 if mirrored else pya.Trans.R0, round(x_nm * 4), 0)
    inst.set_property(1, "ol:" + name)
    return inst


def find(cell, name):
    return [i for i in cell.each_inst() if i.property(1) == "ol:" + name][0]


def info(cell, name):
    i = find(cell, name)
    p = i.pcell_parameters_by_name()
    return round(i.dcplx_trans.disp.x * 1000), bool(p["abut_left"]), bool(p["abut_right"]), i.trans.rot


c = ly.create_cell("CHAIN")
device(c, "MA", 0)
device(c, "MB", 162)                                  # just touching: both dummy gates still there
msgs = chain.update(c, moved=[find(c, "MB")], conn=conn)
check("a transistor dropped next to another snaps into the chain", info(c, "MB")[:3] == (54, True, False)
      and info(c, "MA")[1:3] == (False, True), (info(c, "MA"), info(c, "MB"), msgs))
act = region(ly, c, "active")
check("chained diffusion is one piece, dummies between them gone", act.count() == 1
      and region(ly, c, "gate").count() == 4, (act.count(), region(ly, c, "gate").count()))

device(c, "MC", 54 + 162)                             # touching MB: MB.d = Y, but MC.s = Z, MC.d = X
msgs = chain.update(c, moved=[find(c, "MC")], conn=conn)
check("different diffusion nets do not chain", info(c, "MC")[1:3] == (False, False) and msgs, (info(c, "MC"), msgs))

find(c, "MB").transform(pya.DTrans(0.5, 0))           # move MB away again
chain.update(c, moved=[find(c, "MB")], conn=conn)
check("moving a transistor away restores its dummy gates", info(c, "MA")[1:3] == (False, False)
      and info(c, "MB")[1:3] == (False, False), (info(c, "MA"), info(c, "MB")))

c2 = ly.create_cell("FLIP")
device(c2, "MA", 0)
device(c2, "MC", 162)                                 # touching MA: MA.d = X faces MC.s = Z; MC.d = X
msgs = chain.update(c2, moved=[find(c2, "MC")], conn=conn)
x, al, ar, rot = info(c2, "MC")
check("a transistor is flipped so the shared diffusion nets match", rot == 6 and (al, ar) == (False, True)
      and info(c2, "MA")[2], (info(c2, "MC"), msgs))

c3 = ly.create_cell("PACK")
for name, x in (("MA", 0), ("MB", 500), ("ME", 1000)):
    device(c3, name, x)
msgs = chain.chain(c3, [find(c3, n) for n in ("MA", "MB", "ME")], conn=conn)
cols = [chain.Device(find(c3, n), conn) for n in ("MA", "MB", "ME")]
check("Chain Selected packs transistors into one chain", cols[0].right == cols[1].left and cols[1].right == cols[2].left
      and region(ly, c3, "active").count() == 1 and not msgs, ([(d.left, d.right) for d in cols], msgs))
device(c3, "MC", 2000)                                # MC.s = Z, MC.d = X: nothing matches ME.d = W
msgs = chain.chain(c3, [find(c3, n) for n in ("MA", "MB", "ME", "MC")], conn=conn)
check("Chain Selected leaves a transistor with no matching net where it is", info(c3, "MC")[:3] == (2000, False, False)
      and msgs, (info(c3, "MC"), msgs))

from openlayout_kl.pcells import mos_geometry  # noqa: E402
t = mos_geometry("nmos", 2, 1, abut_right=True, contact_right=False)["terminals"]
check("an uncontacted shared diffusion is a diffusion terminal", t["d"][0][2] == "sd" and t["s"][0][2] == "lisd", t)

# schematic-driven generation into a cell that has a frame: transistors come in row mode at y = 0
import shutil  # noqa: E402
import tempfile  # noqa: E402
sys.path.insert(0, str(HOME / "python"))
from openlayout.workarea import Workarea  # noqa: E402
from openlayout_kl import connectivity, generate  # noqa: E402

wa = Workarea.create(Path(tempfile.mkdtemp()) / "wa", "cpu8")
wlib = wa.library("cpu8")
(wlib.path / "inv").mkdir()
shutil.copy(HOME / "tests/klayout/inv_pins.sch", wlib.path / "inv" / "inv.sch")
gds = wlib.path / "inv" / "inv.gds"
fl = pya.Layout()
fl.dbu = 0.00025
fl.technology_name = "asap7"
ftop = fl.create_cell("inv")
fpc = fl.create_cell("stdcell", LIBRARY, {"cpp": 5})
ftop.insert(pya.DCellInstArray(fpc.cell_index(), pya.DTrans()))
pli = fl.layer(LAYERS["m1"], 251)
ftop.shapes(pli).insert(pya.DText("VSS", pya.DTrans(0.03, 0)))
ftop.shapes(pli).insert(pya.DText("VDD", pya.DTrans(0.03, 0.27)))
fl.write(str(gds))
rep = generate.generate(wlib.path / "inv" / "inv.sch")
gl = pya.Layout()
gl.technology_name = "asap7"
gl.read(str(gds))
gtop = gl.cell("inv")
devs = {connectivity.instance_name(i): i for i in gtop.each_inst() if connectivity.instance_name(i)}
check("generation in a framed cell uses row mode at y = 0",
      sorted(devs) == ["M1", "M2"] and all(i.pcell_parameters_by_name()["row"] and i.dcplx_trans.disp.y == 0
                                           for i in devs.values()), {n: str(i.dcplx_trans) for n, i in devs.items()})
check("rail pins are not added again", sorted(rep["pins_added"]) == ["A", "Y"], rep["pins_added"])
res = connectivity.check(gl, gtop, connectivity.load_conn(gds))
check("connectivity check runs on row-mode devices", not res["missing"] and res["nets"]["VDD"]["terminals"] > 0,
      connectivity.summary(res))

print("PASS stdcell" if not failures else f"FAIL stdcell: {', '.join(failures)}")
