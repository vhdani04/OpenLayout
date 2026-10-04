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

from openlayout_kl import chain, connectivity, stdcell  # noqa: E402
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
FRONT_LIG = FRONT + ["lig"]


def place(cell, name, x_nm, **params):
    pc = ly.create_cell(name, LIBRARY, params)
    return cell.insert(pya.DCellInstArray(pc.cell_index(), pya.DTrans(x_nm / 1000, 0)))


def region(layout, cell, layer):
    li = layout.find_layer(LAYERS[layer], 0)
    return pya.Region() if li is None else pya.Region(cell.begin_shapes_rec(li)).merged()


def compare(cell, ref_name, layers=FRONT):
    ref = lib.cell(ref_name)
    bad = {}
    for layer in layers:
        a = region(ly, cell, layer)
        b = region(lib, ref, layer)
        # the library's gates end at 275 or 275.5 nm: compare within half a nanometre
        x = (a ^ b).sized(-1)
        if not x.is_empty():
            bad[layer] = str(x)[:120]
    return bad


# INVx1: frame of 3 gate pitches, a 3-fin nMOS and pMOS in the same column (one gate through both)
inv = ly.create_cell("INV")
stdcell.draw_frame(inv, 3)
place(inv, "nmos", 0, row=True, nfin=3, nf=1)
place(inv, "pmos", 0, row=True, nfin=3, nf=1)
bad = compare(inv, "INVx1_ASAP7_75t_R", FRONT_LIG)
check("frame + row devices reproduce INVx1 (front-end layers and the gate contact)", not bad, bad)

# NAND2xp33: two 2-fin nMOS chained in series (no contact on the inner node), two 1-fin pMOS chained
# in parallel (sharing the output in the middle)
nand = ly.create_cell("NAND")
stdcell.draw_frame(nand, 4)
place(nand, "nmos", 0, row=True, nfin=2, nf=1, abut_right=True, contact_right=False)
place(nand, "nmos", 54, row=True, nfin=2, nf=1, abut_left=True, contact_left=False)
place(nand, "pmos", 0, row=True, nfin=1, nf=1, abut_right=True)
place(nand, "pmos", 54, row=True, nfin=1, nf=1, abut_left=True)
bad = compare(nand, "NAND2xp33_ASAP7_75t_R")
check("chained series nMOS reproduce NAND2xp33 (front-end layers)", not bad, bad)
lig = region(ly, nand, "lig")
check("the two inputs' gate contacts stay apart", (lig & region(lib, lib.cell("NAND2xp33_ASAP7_75t_R"), "lig")).count() >= 4
      and region(ly, nand, "lig").count() == 4, str(lig)[:200])
pc = ly.create_cell("nmos", LIBRARY, {"nfin": 2, "nf": 1})
check("no GCUT in the transistor PCells", ly.find_layer(LAYERS["gcut"], 0) is None
      or pc.shapes(ly.find_layer(LAYERS["gcut"], 0)).is_empty())

check("the comparison notices differences", bool(compare(inv, "NAND2xp33_ASAP7_75t_R")))
check("the frame is plain shapes in the cell (no instance), tagged as frame",
      not [i for i in nand.each_inst() if not i.is_pcell() or i.pcell_declaration().name() == "stdcell"]
      and len(stdcell.frame_shapes(nand)) > 10 and stdcell.frame_params(nand) == {"cpp": 4, "vt": "rvt"},
      (len(stdcell.frame_shapes(nand)), stdcell.frame_params(nand)))
stdcell.draw_frame(nand, 6, "slvt")
check("drawing the frame again replaces it", stdcell.frame_params(nand) == {"cpp": 6, "vt": "slvt"}
      and region(ly, nand, "boundary").count() == 1, (stdcell.frame_params(nand), region(ly, nand, "boundary").count()))
old = ly.create_cell("OLDFRAME")
place(old, "stdcell", 0, cpp=5)
stdcell.draw_frame(old, 5)
check("an old frame PCell instance is replaced by plain shapes", old.child_instances() == 0
      and stdcell.frame_params(old) == {"cpp": 5, "vt": "rvt"}, old.child_instances())

# the rails: V0 joins LIG and M1 at every gate-pitch column, like the library
for name, cellv, ref in (("INV", inv, "INVx1_ASAP7_75t_R"), ("NAND", nand, "NAND2xp33_ASAP7_75t_R")):
    if name == "NAND":
        stdcell.draw_frame(cellv, 4)
    rails = pya.Region([pya.DBox(-1, -0.010, 10, 0.010).to_itype(ly.dbu), pya.DBox(-1, 0.260, 10, 0.280).to_itype(ly.dbu)])
    ours = region(ly, cellv, "v0") & rails
    rails_lib = pya.Region([pya.DBox(-1, -0.010, 10, 0.010).to_itype(lib.dbu), pya.DBox(-1, 0.260, 10, 0.280).to_itype(lib.dbu)])
    theirs = region(lib, lib.cell(ref), "v0") & rails_lib
    check(f"the frame's rail V0s match {ref}", ours.count() == theirs.count() and ours.count() > 0
          and sorted(str(b.bbox().to_dtype(ly.dbu)) for b in ours.each()) ==
          sorted(str(b.bbox().to_dtype(lib.dbu)) for b in theirs.each()), (ours.count(), theirs.count()))

# LIG and LISD connect where they overlap: a source run into the LIG rail reaches the M1 VSS rail
src = ly.create_cell("SRC")
stdcell.draw_frame(src, 3)
place(src, "nmos", 0, row=True, nfin=2, nf=1)
lisd_li = ly.layer(LAYERS["lisd"], 0)


def same_net(cellv, a, b, la, lb):
    l2n, regs = connectivity.extract(ly, cellv)
    na = l2n.probe_net(regs[la], pya.DPoint(*a))
    nb = l2n.probe_net(regs[lb], pya.DPoint(*b))
    return na is not None and nb is not None and na.cluster_id == nb.cluster_id


check("a source not run into the rail is not on VSS", not same_net(src, (0.054, 0.05), (0.1, 0.0), "lisd", "m1"))
src.shapes(lisd_li).insert(pya.DBox(0.042, 0.0, 0.066, 0.027))       # the source's LISD down into the LIG rail
check("a source's LISD run into the LIG rail is on the M1 VSS rail (LISD - LIG - V0 - M1)",
      same_net(src, (0.054, 0.05), (0.1, 0.0), "lisd", "m1"))
lig_li = ly.layer(LAYERS["lig"], 0)
src.shapes(lig_li).insert(pya.DBox(0.04, 0.124, 0.08, 0.146))        # LIG from the gate strap ...
src.shapes(lig_li).insert(pya.DBox(0.046, 0.06, 0.062, 0.146))       # ... down onto the source contact
check("LIG over a source contact joins it to the gate (a short the check can now see)",
      same_net(src, (0.081, 0.135), (0.054, 0.05), "lig", "lisd"))

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
stdcell.draw_frame(ftop, 5)
fl.write(str(gds))
rep = generate.generate(wlib.path / "inv" / "inv.sch")
gl = pya.Layout()
gl.technology_name = "asap7"
gl.read(str(gds))
gtop = gl.cell("inv")
devs = {connectivity.instance_name(i): i for i in gtop.each_inst() if connectivity.instance_name(i)}
check("generation in a framed cell: row-mode transistors parked below the cell (pMOS, then nMOS)",
      sorted(devs) == ["M1", "M2"] and all(i.pcell_parameters_by_name()["row"] for i in devs.values())
      and [round(devs[n].dcplx_trans.disp.y, 3) for n in ("M1", "M2")] == [-0.54, -0.81],
      {n: str(i.dcplx_trans) for n, i in devs.items()})
check("rail pins are not added again", sorted(rep["pins_added"]) == ["A", "Y"], rep["pins_added"])
# generating a cell without a frame draws one with its boundary at (0, 0); the transistors are
# parked below it, none overlapping
wlib2 = wa.library("cpu8")
(wlib2.path / "inv2").mkdir()
shutil.copy(HOME / "tests/klayout/inv_pins.sch", wlib2.path / "inv2" / "inv2.sch")
generate.generate(wlib2.path / "inv2" / "inv2.sch")
g2 = wlib2.path / "inv2" / "inv2.gds"
l2 = pya.Layout()
l2.technology_name = "asap7"
l2.read(str(g2))
t2 = l2.cell("inv2")
bnd = [s.dbbox() for s in t2.shapes(l2.layer(LAYERS["boundary"], 0)).each()]
boxes = [i.dbbox() for i in t2.each_inst()]
check("a generated transistor cell gets the frame, boundary corner at (0, 0)",
      len(bnd) == 1 and (bnd[0].left, bnd[0].bottom) == (0, 0) and stdcell.frame_params(t2) is not None, bnd)
check("generated transistors sit below the cell, not overlapping each other",
      all(b.top < 0 for b in boxes) and not any(a.overlaps(b) for k, a in enumerate(boxes) for b in boxes[k + 1:]),
      [str(b) for b in boxes])

# an older layout with standalone transistors: updating it gives the frame and parks them as row devices
l3 = pya.Layout()
l3.dbu = 0.00025
l3.technology_name = "asap7"
t3 = l3.create_cell("inv3")
for name, kind, y in (("M1", "pmos", 0.3), ("M2", "nmos", 0.0)):
    old_dev = t3.insert(pya.DCellInstArray(l3.create_cell(kind, LIBRARY, {"nfin": 3, "nf": 2}).cell_index(),
                                           pya.DTrans(0, y)))
    old_dev.set_property(1, "ol:" + name)
(wlib2.path / "inv3").mkdir()
shutil.copy(HOME / "tests/klayout/inv_pins.sch", wlib2.path / "inv3" / "inv3.sch")
rep3 = generate.generate(wlib2.path / "inv3" / "inv3.sch", layout=l3)
moved = {connectivity.instance_name(i): (i.pcell_parameters_by_name()["row"], round(i.dcplx_trans.disp.y, 3))
         for i in t3.each_inst() if connectivity.instance_name(i)}
check("updating an older layout converts its transistors to row devices, parked below the new frame",
      sorted(rep3["updated"]) == ["M1", "M2"] and moved == {"M1": (True, -0.54), "M2": (True, -0.81)}
      and stdcell.frame_params(t3) is not None, (rep3["updated"], moved))

# the ground net is VSS: a schematic with xschem's stock ground (lab=0) and global VDD, like the
# demo cells, links to the layout with VSS - and VDD / VSS are supply pins (the frame's rails)
assert generate.ground_to_vss("0") == "VSS" and generate.ground_to_vss("GND") == "VSS"
(wlib2.path / "invg").mkdir()
shutil.copy(HOME / "tests/klayout/inv_globals.sch", wlib2.path / "invg" / "invg.sch")
repg = generate.generate(wlib2.path / "invg" / "invg.sch")
cg = connectivity.load_conn(wlib2.path / "invg" / "invg.gds")
nets = {t for spec in cg["instances"].values() for t in spec["terminals"].values()}
check("the stock ground (0) becomes VSS in the schematic link", "VSS" in nets and "0" not in nets, sorted(nets))
check("the cell's global VDD / VSS are supply pins of the layout (the frame's rails)",
      {"VDD", "VSS"} <= set(cg["pins"]) and "VDD" not in repg["pins_added"] and "VSS" not in repg["pins_added"],
      (cg["pins"], repg["pins_added"]))
lg = pya.Layout()
lg.technology_name = "asap7"
lg.read(str(wlib2.path / "invg" / "invg.gds"))
resg = connectivity.check(lg, lg.cell("invg"), cg)
check("the connectivity check sees the VSS rail as the ground net's pin",
      "VSS" in resg["nets"] and resg["nets"]["VSS"]["terminals"] >= 2
      and "0" not in resg["nets"], {n: v["terminals"] for n, v in resg["nets"].items()})

pin_li = lg.find_layer(LAYERS["m1"], 251)
pin_boxes = [sh.dbbox() for sh in lg.cell("invg").shapes(pin_li).each() if sh.is_box()]
m1_draw = pya.Region(lg.cell("invg").shapes(lg.find_layer(LAYERS["m1"], 0)))
check("generated pins are minimum-width (18 nm) M1 pin squares with no drawing shape under them",
      len(pin_boxes) == 2 and all(abs(b.width() - 0.018) < 1e-9 and abs(b.height() - 0.018) < 1e-9 for b in pin_boxes)
      and not any(m1_draw.interacting(pya.Region(b.to_itype(lg.dbu))).count() for b in pin_boxes),
      [str(b) for b in pin_boxes])

# a row transistor dropped onto the cell goes onto the row and the gate grid
c4 = ly.create_cell("SNAP")
stdcell.draw_frame(c4, 6)
dev = c4.insert(pya.DCellInstArray(ly.create_cell("nmos", LIBRARY, {"row": True, "nfin": 2, "nf": 1}).cell_index(),
                                   pya.DTrans(0.07, 0.06)))
chain.update(c4, moved=[dev])
d4 = list(c4.each_inst())[0].dcplx_trans.disp
check("a row transistor dropped onto the cell snaps onto the row and the 54 nm grid",
      (round(d4.x, 4), round(d4.y, 4)) == (0.054, 0.0), str(d4))
c4.each_inst().__next__().transform(pya.DTrans(0.01, -0.5))
chain.update(c4, moved=list(c4.each_inst()))
d4 = list(c4.each_inst())[0].dcplx_trans.disp
check("one dropped outside the cell keeps its height (grid only)", (round(d4.x, 4), round(d4.y, 4)) == (0.054, -0.5), str(d4))

res = connectivity.check(gl, gtop, connectivity.load_conn(gds))
check("connectivity check runs on row-mode devices", not res["missing"] and res["nets"]["VDD"]["terminals"] > 0,
      connectivity.summary(res))

print("PASS stdcell" if not failures else f"FAIL stdcell: {', '.join(failures)}")
