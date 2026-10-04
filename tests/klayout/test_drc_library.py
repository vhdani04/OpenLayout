# The ASAP7 7.5T standard cells must be DRC-clean with the deck, placed as in a design: each cell
# between two INVx1 in its row, with the cell flipped in the rows below and above (abutment is
# where many rules live: wells, implants, diffusion breaks, rails). Markers count for a cell when
# they lie in it or on its edges. KLayout batch mode:
#   klayout -b -r tests/klayout/test_drc_library.py [-rd libs=R,L,SL,SRAM]
#
# Known library waivers (the cells break the DRM as written):
#   SDT.ACTIVE.AUX.2  OAI22xp33: its source/drain trenches are 81 nm tall over 54 nm ACTIVE.
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import pya

HOME = Path(os.environ["OPENLAYOUT_HOME"])
DECK = HOME / "pdk/asap7/klayout/drc/asap7.drc"
GDS = Path(os.environ.get("ASAP7_STDCELLS", HOME.parent / "pdk/asap7/asap7sc7p5t_28")) / "GDS"
WAIVERS = {("OAI22xp33", "SDT.ACTIVE.AUX.2")}
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def run(vt):
    src = pya.Layout()
    src.read(str(GDS / f"asap7sc7p5t_28_{vt}_220121a.gds"))
    dbu = src.dbu
    names = sorted(c.name for c in src.top_cells())
    inv_name = next(n for n in names if n.startswith("INVx1_"))
    out = pya.Layout()
    out.dbu = dbu
    top = out.create_cell("CTX")
    bl = src.find_layer(100, 0)
    gap = round(1.08 / dbu)                     # between blocks: whole gate pitches and rows
    width = lambda c: pya.Region(c.begin_shapes_rec(bl)).bbox().width()
    inv = out.create_cell(inv_name)
    inv.copy_tree(src.cell(inv_name))
    iw = width(src.cell(inv_name))
    blocks = {}
    x0 = y0 = 0
    for name in names:
        c = src.cell(name)
        bb = pya.Region(c.begin_shapes_rec(bl)).bbox()
        cw = bb.width()
        ci = out.cell(name) or out.create_cell(name)
        if ci.is_empty():
            ci.copy_tree(c)
        x = x0 + iw
        for t in (pya.Trans(x0, y0), pya.Trans(x + cw, y0)):
            top.insert(pya.CellInstArray(inv.cell_index(), t))
        for t in (pya.Trans(x, y0), pya.Trans(pya.Trans.M0, x, y0), pya.Trans(pya.Trans.M0, x, y0 + 2 * bb.height())):
            top.insert(pya.CellInstArray(ci.cell_index(), t))
        blocks[name] = pya.Box(x, y0, x + cw, y0 + bb.height())
        x0 += 2 * iw + cw + gap
        if x0 > round(40.0 / dbu):
            x0, y0 = 0, y0 + round(2.16 / dbu)
    tmp = Path(tempfile.mkdtemp())
    out.write(str(tmp / "ctx.gds"))
    rep = tmp / "ctx.lyrdb"
    res = subprocess.run(["klayout", "-b", "-r", str(DECK), "-rd", f"input={tmp / 'ctx.gds'}", "-rd", "topcell=CTX",
                          "-rd", f"report={rep}"], capture_output=True, text=True)
    check(f"{vt}: the deck runs", res.returncode == 0, (res.stdout + res.stderr)[-400:])
    rdb = pya.ReportDatabase("")
    rdb.load(str(rep))
    per_cell = defaultdict(Counter)
    for item in rdb.each_item():
        rule = rdb.category_by_id(item.category_id()).name()
        for v in item.each_value():
            b = (v.box() if v.is_box() else v.edge_pair().bbox() if v.is_edge_pair() else v.edge().bbox()
                 if v.is_edge() else v.polygon().bbox() if v.is_polygon() else None)
            if b is None:
                continue
            centre = pya.Point(round(b.center().x / dbu), round(b.center().y / dbu))
            for name, blk in blocks.items():
                if blk.contains(centre):
                    per_cell[name][rule] += 1
                    break
    bad = {}
    for name, rules in per_cell.items():
        base = name.rsplit("_ASAP7", 1)[0]
        left = {r: n for r, n in rules.items() if (base, r) not in WAIVERS}
        if left:
            bad[name] = dict(left)
    check(f"{vt}: all {len(names)} cells DRC-clean in context (waivers: {len(WAIVERS)})", not bad,
          "; ".join(f"{n}: {r}" for n, r in list(bad.items())[:6]))


for vt in (globals().get("libs") or "R").split(","):
    run(vt.strip())
print("PASS drc_library" if not failures else f"FAIL drc_library: {', '.join(failures)}")
