# Layer Grid (OpenLayout > Show Layer Grid…), run in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_layer_grid.py
# The grid table is read from the DRC deck and the tech / library LEF; the library cells' fins,
# gates and M2 wires must lie on it; the overlay is markers only and follows zoom and pan.
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import gui, layer_grid as lg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def near(a, b):
    return a is not None and abs(a - b) < 1e-9


# ---- the table, from the sources ----------------------------------------------------------------
t = lg.grid_table(reload=True)
expect = {   # layer: (kind, horizontal, pitch, offset) in um
    "fin": ("drc", True, 0.027, 0.0135), "gate": ("drc", False, 0.054, 0.027),
    "m1": ("lef", False, 0.036, 0.0), "m3": ("lef", False, 0.036, 0.0),
    "m4": ("drc", True, 0.048, 0.012), "m5": ("drc", False, 0.048, 0.012),
    "m6": ("drc", True, 0.064, 0.016), "m7": ("drc", False, 0.064, 0.016),
}
for key, (kind, hor, pitch, offset) in expect.items():
    g = t[key]
    check(f"{key}: {kind}, {'horizontal' if hor else 'vertical'}, {pitch * 1000:g} + offset {offset * 1000:g} nm",
          g.kind == kind and g.horizontal == hor and near(g.pitch, pitch) and near(g.offset, offset),
          (g.kind, g.horizontal, g.pitch, g.offset))
m2 = t["m2"]
check("m2: per 270 nm row, 45 nm from the rails then 36 nm pitch",
      m2.kind == "lef" and m2.horizontal and m2.row is not None and near(m2.row[0], 0.27)
      and [round(y * 1000, 3) for y in m2.row[1]] == [45, 81, 117, 153, 189, 225], m2.row)
for key in ("m8", "m9"):
    check(f"{key}: no offset in any source - flagged, not drawn", t[key].kind == "none" and not t[key].drawable
          and "OFFSET" in t[key].note, t[key].note)
check("min widths from the sources", [round(t[k].width * 1000) for k in ("fin", "gate", "m1", "m2", "m4", "m6")]
      == [7, 20, 18, 18, 24, 32])
check("M4 notes the tech LEF's different OFFSET", "OFFSET 3 nm" in t["m4"].note, t["m4"].note)
check("every drawn layer cites its source", all(g.source for g in t.values() if g.drawable))
check("positions", t["gate"].positions(0, 0.2) == [0.027, 0.081, 0.135, 0.189]
      and m2.positions(0.2, 0.33) == [0.225, 0.315], (t["gate"].positions(0, 0.2), m2.positions(0.2, 0.33)))

# ---- library cells sit on the grid ----------------------------------------------------------------
lib_gds = Path(os.environ["ASAP7_STDCELLS"]) / "GDS" / "asap7sc7p5t_28_R_220121a.gds"
lib = pya.Layout()
lib.read(str(lib_gds))


def centres(cell, gds_layer, horizontal, width):
    """centrelines (um) of the minimum-width pieces of a layer in a cell"""
    r = pya.Region(cell.begin_shapes_rec(lib.layer(gds_layer, 0))).merged()
    out = []
    for poly in r.each():
        for piece in poly.decompose_convex():
            b = piece.bbox().to_dtype(lib.dbu)
            across = b.height() if horizontal else b.width()
            if abs(across - width) < 1e-6:
                out.append(b.center().y if horizontal else b.center().x)
    return out


# every cell of the library: fins, gates and M2 wires on the drawn lines (M1 has no DRC grid and
# the cells do not use the LEF's M1 router tracks - see docs/KEYS.md, Layer grid)
for key, gds_layer in (("fin", 2), ("gate", 7), ("m2", 20)):
    g = t[key]
    n, off = 0, []
    for c in lib.each_cell():
        if c.is_top():
            for x in centres(c, gds_layer, g.horizontal, g.width):
                n += 1
                if not g.on_grid(x):
                    off.append(f"{c.name} {x * 1000:g}")
    check(f"library: every {key} piece on its grid ({n} pieces)", n > 0 and not off, off[:5])


# ---- the overlay -----------------------------------------------------------------------------------
app = pya.Application.instance()
mw = app.main_window()
gui.start(mw)
menu = mw.menu()
check("menu entry", menu.is_valid("openlayout_menu.layer_grid")
      and menu.action("openlayout_menu.layer_grid").title == "Show Layer Grid…")
check("clear entry", menu.is_valid("openlayout_menu.clear_layer_grid"))
check("toolbar button", "@toolbar.openlayout_layer_grid" in menu.items("@toolbar"))


def pump(n=20):
    for _ in range(n):
        app.process_events()


gds = Path(tempfile.mkdtemp()) / "inv.gds"
inv = pya.Layout()
inv.dbu = lib.dbu
top = inv.create_cell("TOP")
src = lib.cell("INVx1_ASAP7_75t_R")
cp = inv.create_cell(src.name)
cp.copy_tree(src)
top.insert(pya.DCellInstArray(cp.cell_index(), pya.DTrans(0, False, 0.216, 0.27)))   # second row, 4 CPP
inv.write(str(gds))
mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
pump()
view.max_hier()
view.zoom_box(pya.DBox(0.2, 0.25, 0.4, 0.56))
pump()
shapes_before = sum(c.shapes(li).size() for c in view.active_cellview().layout().each_cell()
                    for li in view.active_cellview().layout().layer_indexes())

p = lg.painter()
form = lg.open_form(mw, gui.UI)
pump()
check("window lists every layer, M8 / M9 disabled", set(form.boxes) == set(lg.ORDER)
      and not form.boxes["m8"].enabled and form.boxes["m4"].enabled)
form.boxes["gate"].checked = True                       # ticking draws at once
form.boxes["fin"].checked = True
pump()
check("ticked layers are shown", lg.shown() == {"gate", "fin"}, lg.shown())
xs = sorted({round(e.p1.x, 6) for k, e in p.lines if k == "gate"})
inv_gates = [round(0.216 + x, 6) for x in centres(src, 7, False, 0.02)]
check("gate lines through the placed cell's gates", inv_gates and all(x in xs for x in inv_gates), (inv_gates, xs[:8]))
ys = sorted({round(e.p1.y, 6) for k, e in p.lines if k == "fin"})
inv_fins = [round(0.27 + y, 6) for y in centres(src, 2, True, 0.007)]
check("fin lines through the placed cell's fins", all(y in ys for y in inv_fins), inv_fins)
check("lines span the view", all(e.p1.y <= view.box().bottom and e.p2.y >= view.box().top
                                 for k, e in p.lines if k == "gate"))

lg.show(["m2"])
pump()
ys = sorted({round(e.p1.y, 6) for k, e in p.lines if k == "m2"})
check("m2 tracks of the second row", all(y in ys for y in (0.315, 0.351, 0.495)), ys)
check("the window follows show()", form.boxes["m2"].checked and not form.boxes["gate"].checked)

# pan: the lines move along
lg.show(["gate"])
pump()
view.zoom_box(pya.DBox(5.2, 0.25, 5.4, 0.56))
pump(10)
p.redraw()
xs = sorted({round(e.p1.x, 6) for k, e in p.lines if k == "gate"})
check("pan redraws the lines where the view is", xs and min(xs) < 5.2 and max(xs) > 5.4 and 5.211 in xs, xs[:3])

# zoomed far out: too dense, left out (and said so)
view.zoom_box(pya.DBox(-50, -50, 50, 50))
pump(10)
p.redraw()
check("too dense at this zoom: not drawn", not p.lines and p.hidden == ["gate"], (len(p.lines), p.hidden))
form.sync()
check("the window says to zoom in", "GATE" in form.status.text, form.status.text)
view.zoom_box(pya.DBox(0.2, 0.25, 0.4, 0.56))
pump(10)
p.redraw()
check("zoomed in again: drawn", p.lines and not p.hidden)

# markers only: nothing in the layout, nothing selectable
shapes_after = sum(c.shapes(li).size() for c in view.active_cellview().layout().each_cell()
                   for li in view.active_cellview().layout().layer_indexes())
check("no shapes added to the layout", shapes_before == shapes_after, (shapes_before, shapes_after))
view.select_all()
picked = list(view.each_object_selected())
check("select all picks only the cell instance", len(picked) == 1 and picked[0].is_cell_inst(), len(picked))
view.clear_selection()

# Clear (button / menu)
menu.action("openlayout_menu.clear_layer_grid").trigger()
pump()
check("Clear Layer Grid removes every line", not p.lines and not p.markers and not lg.shown())
form.all()
pump()
check("All shows every drawable layer", lg.shown() == {k for k, g in t.items() if g.drawable})
form.clear()
pump()
check("Clear button", not lg.shown() and not form.boxes["fin"].checked)

print("PASS layer_grid" if not failures else f"FAIL layer_grid: {', '.join(failures)}")
