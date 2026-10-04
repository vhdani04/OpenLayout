# DRD spacing hints: the rule values per layer, and the hints while drawing a path, drawing a box
# and moving a shape (real mouse input through LayoutView.send_mouse_*), in KLayout with a main
# window (headless):
#   klayout -e -z -nc -r tests/klayout/test_drd.py
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import drd, gui  # noqa: E402
from openlayout_kl.path_tool import PathTool  # noqa: E402

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

# off: no hints
drd.set_enabled(False)
tool.mouse_click_event(pya.DPoint(-0.05, 0.12), L, True)
tool.mouse_moved_event(pya.DPoint(0.12, 0.12), 0, True)
check("DRD switched off in the menu: no hints", not shown.markers)
tool.key_event(pya.KeyCode.Escape, 0)
drd.set_enabled(True)
check("the menu has the DRD switch", mw.menu().is_valid("openlayout_menu.drd"))

print("PASS drd" if not failures else f"FAIL drd: {', '.join(failures)}")
