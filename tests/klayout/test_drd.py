# DRD spacing hints: the rule values per layer and between layers, and the hints in every editing
# tool - path, box, polygon, stretch, move, copy, instance and via placement (real mouse input
# through LayoutView.send_mouse_*), in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_drd.py
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import drag_move, drd, gui  # noqa: E402
from openlayout_kl.path_tool import PathTool  # noqa: E402
from openlayout_kl.pcells import via_geometry  # noqa: E402
from openlayout_kl.vias import ViaPlacer  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


# ---- rule values (no GUI needed) -------------------------------------------------------------
ly = pya.Layout()
ly.dbu = 0.00025
c = ly.create_cell("T")


def hits(layer, static, moving):
    li = ly.layer(layer, 0)
    c.shapes(li).clear()
    for b in static:
        c.shapes(li).insert(pya.DBox(*[v / 1000 for v in b]))
    return [(round(h[3], 1), round(h[4], 1)) for h in
            drd.check(c, li, [pya.DPolygon(pya.DBox(*[v / 1000 for v in b])) for b in moving])]


check("M1 side to side: 10 nm where 18 are needed", hits(19, [(0, 0, 18, 100)], [(28, 0, 46, 100)]) == [(18, 10)])
check("M1 side to side at 20 nm: fine", hits(19, [(0, 0, 18, 100)], [(38, 0, 56, 100)]) == [])
check("M1 line end to side: 25 nm", hits(19, [(0, 120, 200, 138)], [(0, 0, 18, 100)]) == [(25, 20)])
check("M1 line ends (18 nm wide): 31 nm", hits(19, [(0, 0, 18, 100)], [(0, 128, 18, 228)]) == [(31, 28)])
check("M1 line ends 32 nm apart: fine", hits(19, [(0, 0, 18, 100)], [(0, 132, 18, 232)]) == [])
check("M1 corner to corner: 20 nm", hits(19, [(0, 0, 40, 40)], [(50, 50, 90, 90)]) == [(20, 14.1)])
check("M4 across the tracks 24 nm, along them 40 nm",
      hits(40, [(0, 0, 200, 24)], [(0, 44, 200, 68)]) == [(24, 20)]
      and hits(40, [(0, 0, 100, 24)], [(130, 0, 230, 24)]) == [(40, 30)])
check("V1 vias: 18 nm", hits(21, [(0, 0, 18, 18)], [(33, 0, 51, 18)]) == [(18, 15)])
check("gates: 34 nm", hits(7, [(17, 0, 37, 300)], [(67, 0, 87, 300)]) == [(34, 30)])
check("a touching shape is the same net: no hint", hits(19, [(0, 0, 18, 100)], [(18, 40, 60, 58)]) == [])
check("layers without spacing rules: no hint", hits(12, [(0, 0, 100, 100)], [(105, 0, 200, 100)]) == [])


def hits2(layer, static, moving):
    """moving shapes on `layer` against static {layer: [boxes]}: [(required, actual, label)]"""
    for li in c.layout().layer_indexes():
        c.shapes(li).clear()
    for num, boxes in static.items():
        for b in boxes:
            c.shapes(ly.layer(num, 0)).insert(pya.DBox(*[v / 1000 for v in b]))
    return [(round(h[3], 1), round(h[4], 1), h[5]) for h in
            drd.check(c, ly.layer(layer, 0), [pya.DPolygon(pya.DBox(*[v / 1000 for v in b])) for b in moving])]


check("between layers: LIG 10 nm from LISD needs 14", hits2(16, {17: [(26, 0, 50, 100)]}, [(0, 0, 16, 100)])
      == [(14, 10, "14 nm min to LISD")])
check("between layers: LIG overlapping LISD (connected): no hint",
      hits2(16, {17: [(10, 0, 34, 100)]}, [(0, 0, 16, 100)]) == [])
check("between layers: SDT 3 nm from a gate needs 5", hits2(88, {7: [(71, 0, 91, 300)]}, [(44, 0, 68, 81)])
      == [(5, 3, "5 nm min to GATE")])
check("between layers: a gate 5 nm from ACTIVE needs 9 (the other way round too)",
      hits2(7, {11: [(42, 27, 116, 108)]}, [(17, -50, 37, 300)]) == [(9, 5, "9 nm min to GATE".replace("GATE", "ACTIVE"))]
      and hits2(11, {7: [(17, -50, 37, 300)]}, [(42, 27, 116, 108)]) == [(9, 5, "9 nm min to GATE")])
check("between layers: LIG 10 nm above a gate end needs 14", hits2(16, {7: [(17, 0, 37, 200)]}, [(0, 210, 160, 226)])
      == [(14, 10, "14 nm min to GATE")])
check("between layers: ACTIVE 20 nm from WELL needs 27", hits2(11, {1: [(0, 0, 300, 300)]}, [(0, 320, 200, 401)])
      == [(27, 20, "27 nm min to WELL")])
check("between layers: LIG and LISD corner to corner, 15 nm", hits2(16, {17: [(26, 110, 50, 210)]}, [(0, 0, 16, 100)])
      == [(15, 14.1, "15 nm min to LISD")])

# ---- in the editor ----------------------------------------------------------------------------
mw = pya.Application.instance().main_window()
gui.start(mw)
gds = Path(tempfile.mkdtemp()) / "d.gds"
ly = pya.Layout()
ly.dbu = 0.00025
top = ly.create_cell("TOP")
m1 = ly.layer(19, 0)
top.shapes(m1).insert(pya.DBox(0, 0, 0.1, 0.1))          # A
top.shapes(m1).insert(pya.DBox(0.2, 0, 0.3, 0.1))        # B
ly.write(str(gds))
mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.max_hier()
view.zoom_box(pya.DBox(-0.1, -0.1, 0.5, 0.3))
it = view.begin_layers()
while not it.at_end():
    if it.current().source_layer == 19 and it.current().source_datatype == 0 and not it.current().has_children():
        view.current_layer = it
        break
    it.next()
cell = view.active_cellview().cell
L = pya.ButtonState.LeftButton
shown = drd.display(view)


def px(x, y):
    q = view.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, view.viewport_height() - q.y)


def labels():
    return [a.fmt for a in shown.rulers if a.is_valid()]


# a path drawn along A's top, 11 nm above it
tool = PathTool(view)
tool.mouse_click_event(pya.DPoint(-0.05, 0.12), L, True)
tool.mouse_moved_event(pya.DPoint(0.12, 0.12), 0, True)
check("drawing a path 11 nm from a wire: the gap is outlined, labelled with the minimum",
      len(shown.markers) >= 1 and "18 nm min" in labels(), labels())
tool.mouse_moved_event(pya.DPoint(-0.05, 0.4), 0, True)       # turned up, away from A
check("further away: the hint goes", not shown.markers and not labels(), labels())
tool.key_event(pya.KeyCode.Escape, 0)
check("the path cancelled: no hints left", not shown.markers)

# a box drawn in Box mode, 15 nm right of A (click - move - click)
view.switch_mode("box")
q = px(0.115, 0.0)
view.send_mouse_move_event(q, 0)
view.send_mouse_press_event(q, L)
view.send_mouse_release_event(q, L)
view.send_mouse_move_event(px(0.15, 0.1), 0)
check("drawing a box 15 nm from a wire: hint", "18 nm min" in labels() and shown.markers, labels())
q = px(0.15, 0.1)
view.send_mouse_press_event(q, L)
view.send_mouse_release_event(q, L)
check("the box placed: hints cleared", not shown.markers and not labels(), labels())
view.send_mouse_move_event(px(0.4, 0.25), 0)
boxes = [s.dbbox() for s in cell.shapes(m1).each()]
check("the box itself is drawn as usual (hints only, no constraint)",
      any(abs(b.left - 0.115) < 1e-6 and abs(b.right - 0.15) < 1e-6 for b in boxes), [str(b) for b in boxes])
view.transaction("undo box")
for s in list(cell.shapes(m1).each()):
    if abs(s.dbbox().left - 0.115) < 1e-6:
        s.delete()
view.commit()

# Esc while drawing a box: the hint goes with it
q = px(0.115, 0.0)
view.send_mouse_move_event(q, 0)
view.send_mouse_press_event(q, L)
view.send_mouse_release_event(q, L)
view.send_mouse_move_event(px(0.15, 0.1), 0)
had = bool(shown.markers)
canvas = [w for w in view.widget().children() if type(w).__name__ == "QWidget_Native"][0]
pya.QCoreApplication.sendEvent(canvas, pya.QKeyEvent(pya.QEvent.KeyPress, pya.Qt.Key_Escape.to_i(), pya.Qt.NoModifier))
for _ in range(5):
    pya.Application.instance().process_events()
view.send_mouse_move_event(px(0.16, 0.1), 0)
check("Esc while drawing a box clears the hint", had and not shown.markers and not labels(), labels())

# moving B towards A: the hint follows the drag, the drop clears it
view.switch_mode("select")
view.clear_selection()
q = px(0.25, 0.05)
view.send_mouse_move_event(q, 0)
view.send_mouse_press_event(q, L)
view.send_mouse_release_event(q, L)
pa, pb = px(0.25, 0.05), px(0.16, 0.05)
view.send_mouse_move_event(pa, 0)
view.send_mouse_press_event(pa, L)
for i in range(1, 7):
    view.send_mouse_move_event(pa + (pb - pa) * (i / 6), L)
check("moving a shape to 10 nm from another: hint while dragging", "18 nm min" in labels(), labels())
view.send_mouse_release_event(pb, L)
view.send_mouse_move_event(pb + pya.DVector(40, 40), 0)
check("the drop clears the hint", not shown.markers and not labels(), labels())

B = pya.DBox(0.2, 0, 0.3, 0.1)


def restore():
    """A and B only"""
    view.switch_mode("select")
    view.clear_selection()
    for s in list(cell.shapes(m1).each()):
        if s.dbbox() != pya.DBox(0, 0, 0.1, 0.1):
            s.delete()
    cell.shapes(m1).insert(B)


def click(x, y):
    q = px(x, y)
    view.send_mouse_move_event(q, 0)
    view.send_mouse_press_event(q, L)
    view.send_mouse_release_event(q, L)


def esc():
    pya.QCoreApplication.sendEvent(canvas, pya.QKeyEvent(pya.QEvent.KeyPress, pya.Qt.Key_Escape.to_i(),
                                                         pya.Qt.NoModifier))
    for _ in range(5):
        pya.Application.instance().process_events()


restore()

# a polygon drawn in Polygon mode, its left side 15 nm from A
view.switch_mode("polygon")
for x, y in ((0.115, 0.0), (0.15, 0.0), (0.15, 0.1)):
    click(x, y)
view.send_mouse_move_event(px(0.115, 0.1), 0)
check("drawing a polygon 15 nm from a wire: hint", "18 nm min" in labels(), labels())
q = px(0.115, 0.1)
view.send_mouse_press_event(q, L)
view.send_mouse_release_event(q, L)
dbl = pya.QMouseEvent(pya.QEvent.MouseButtonDblClick, pya.QPointF(q.x, q.y), pya.Qt.LeftButton,
                      pya.Qt.LeftButton, pya.Qt.NoModifier)
pya.QCoreApplication.sendEvent(canvas, dbl)
for _ in range(5):
    pya.Application.instance().process_events()
view.send_mouse_move_event(px(0.4, 0.25), 0)
check("the polygon finished (double click): hints cleared", not shown.markers and not labels(), labels())
restore()

# stretching B's left edge (s) to 15 nm from A, then placing it
view.send_mouse_move_event(px(0.2, 0.05), 0)
drag_move.stretch_under_mouse()
view.send_mouse_move_event(px(0.15, 0.05), 0)
view.send_mouse_move_event(px(0.115, 0.05), 0)
check("stretching an edge to 15 nm from a wire: hint", "18 nm min" in labels(), labels())
click(0.115, 0.05)
view.send_mouse_move_event(px(0.4, 0.25), 0)
check("the stretch placed: hints cleared", not shown.markers and not labels(), labels())
restore()

# KLayout's Partial tool: press on B's left edge, drag it to 15 nm from A, release
view.switch_mode("partial")
pa, pb = px(0.2, 0.05), px(0.115, 0.05)
view.send_mouse_move_event(pa, 0)
view.send_mouse_press_event(pa, L)
for i in range(1, 7):
    view.send_mouse_move_event(pa + (pb - pa) * (i / 6), L)
check("dragging an edge in Partial mode to 15 nm from a wire: hint", "18 nm min" in labels(), labels())
view.send_mouse_release_event(pb, L)
view.send_mouse_move_event(px(0.4, 0.25), 0)
check("the edge released: hints cleared", not shown.markers and not labels(), labels())
restore()

# copying B (c) to 10 nm from A: the copy is checked, the original stays an obstacle
click(0.25, 0.05)
view.send_mouse_move_event(px(0.25, 0.05), 0)
mw.menu().action("@secrets.duplicate_interactive").trigger()
pa, pb = px(0.25, 0.05), px(0.16, 0.05)
for i in range(1, 7):
    view.send_mouse_move_event(pa + (pb - pa) * (i / 6), 0)
check("copying a shape to 10 nm from another: hint while placing the copy", "18 nm min" in labels(), labels())
esc()
view.send_mouse_move_event(px(0.4, 0.25), 0)
check("Esc ends the copy: hints cleared", not shown.markers and not labels(), labels())
restore()

# Instance mode: a cell with an M1 square, its corner at the mouse 15 nm right of A
layout = view.active_cellview().layout()
sub = layout.create_cell("SUB")
sub.shapes(layout.layer(19, 0)).insert(pya.DBox(0, 0, 0.05, 0.05))
mw.set_config("edit-inst-cell-name", "SUB")
view.switch_mode("instance")
view.send_mouse_move_event(px(0.115, 0.0), 0)
check("placing an instance 15 nm from a wire: hint", "18 nm min" in labels(), labels())
view.switch_mode("select")
view.send_mouse_move_event(px(0.4, 0.25), 0)
check("leaving Instance mode clears the hint", not shown.markers and not labels(), labels())

# the via placer (o): an M1-M2 via whose M1 pad comes 11 nm from A
placer = ViaPlacer(view)
geo = via_geometry("m1", "m2")
placer.boxes = [(lay, pya.DBox(*[v / 1000 for v in b])) for lay, bs in geo["shapes"].items() for b in bs]
placer.show(pya.DPoint(0.12, 0.05))
check("placing a via 11 nm from a wire: hint (the pad's 28 nm side is a line end: 25 nm)", "25 nm min" in labels(),
      labels())
drd.clear(view)

# off: no hints
drd.set_enabled(False)
tool.mouse_click_event(pya.DPoint(-0.05, 0.12), L, True)
tool.mouse_moved_event(pya.DPoint(0.12, 0.12), 0, True)
check("DRD switched off in the menu: no hints", not shown.markers)
tool.key_event(pya.KeyCode.Escape, 0)
drd.set_enabled(True)
check("the menu has the DRD switch", mw.menu().is_valid("openlayout_menu.drd"))

print("PASS drd" if not failures else f"FAIL drd: {', '.join(failures)}")
