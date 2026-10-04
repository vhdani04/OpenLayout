# Virtuoso-style drag and drop in Select mode, run in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_drag_move.py
# Mouse input goes through LayoutView.send_mouse_* - the same dispatch as real mouse events.
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import gui  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)

gds = Path(tempfile.mkdtemp()) / "d.gds"
ly = pya.Layout()
ly.dbu = 0.00025
top = ly.create_cell("TOP")
sub = ly.create_cell("SUB")
sub.shapes(ly.layer(19, 0)).insert(pya.DBox(0, 0, 0.1, 0.1))                    # M1 in a sub cell
top.insert(pya.DCellInstArray(sub.cell_index(), pya.DTrans(0, 0)))
top.shapes(ly.layer(20, 0)).insert(pya.DBox(0.3, 0, 0.4, 0.1))                  # an M2 box
ly.write(str(gds))

mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.max_hier()
view.zoom_box(pya.DBox(-0.2, -0.3, 0.6, 0.4))
view.switch_mode("select")
cell = view.active_cellview().cell
L = pya.ButtonState.LeftButton


def px(x, y):
    """micrometers -> widget pixels (y down)"""
    q = view.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, view.viewport_height() - q.y)


def drag(a, b, steps=6):
    pa, pb = px(*a), px(*b)
    view.send_mouse_move_event(pa, 0)
    view.send_mouse_press_event(pa, L)
    for i in range(1, steps + 1):
        view.send_mouse_move_event(pa + (pb - pa) * (i / steps), L)
    view.send_mouse_release_event(pb, L)
    view.send_mouse_move_event(pb + pya.DVector(40, 40), 0)   # a dropped object no longer follows


def m2_box():
    return [s.dbbox() for s in cell.shapes(ly.layer(20, 0)).each()][0]


def inst_pos():
    return [i.dcplx_trans.disp for i in cell.each_inst()][0]


drag((0.35, 0.05), (0.45, 0.05))
b = m2_box()
check("dragging a shape moves it, release drops it", abs(b.left - 0.4) < 1e-6 and abs(b.bottom) < 1e-6, b)
check("the dragged shape stays selected", view.has_object_selection())
check("still in Select mode after a drag", view.mode_name() == "select", view.mode_name())

drag((0.05, 0.05), (0.05, -0.15))
d = inst_pos()
check("dragging an instance moves it", abs(d.x) < 1e-6 and abs(d.y + 0.2) < 1e-6, d)

mw.cm_undo()
check("a drag is one undo step", inst_pos().y == 0 and abs(m2_box().left - 0.4) < 1e-6, (str(inst_pos()), str(m2_box())))

view.clear_selection()
before = (m2_box(), inst_pos())
drag((-0.15, 0.3), (0.2, 0.2))
check("a drag on empty space moves nothing", (m2_box(), inst_pos()) == before)

p = px(0.45, 0.05)
view.send_mouse_move_event(p, 0)
view.send_mouse_press_event(p, L)
view.send_mouse_release_event(p, L)
view.send_mouse_move_event(p + pya.DVector(60, 0), 0)
check("a click selects without moving", view.has_object_selection() and m2_box() == before[0])



def canvas_cursor():
    """cursor of the drawing canvas (the plain QWidget directly under the view widget)"""
    return [str(c.cursor.shape) for c in view.widget().children() if type(c).__name__ == "QWidget_Native"]


view.send_mouse_move_event(px(0.45, 0.05), 0)                 # over the selected M2 box
check("four-way move cursor over the selection", "SizeAllCursor" in canvas_cursor(), canvas_cursor())
view.send_mouse_move_event(px(-0.15, 0.3), 0)                 # empty space
check("normal cursor away from the selection", "SizeAllCursor" not in canvas_cursor(), canvas_cursor())

# m over a shape: it follows the mouse, a click drops it, and the editor is back in Select mode
view.clear_selection()
start = m2_box()
view.send_mouse_move_event(px(0.45, 0.05), 0)
mw.menu().action("openlayout_menu.move").trigger()               # the m key
for x in (0.47, 0.5, 0.55):
    view.send_mouse_move_event(px(x, 0.05), 0)
q = px(0.55, 0.05)
view.send_mouse_press_event(q, L)
view.send_mouse_release_event(q, L)
view.send_mouse_move_event(px(-0.15, 0.3), 0)
moved = m2_box()
check("m moves the shape under the mouse", abs(moved.left - start.left - 0.1) < 1e-6, (str(start), str(moved)))
check("back in Select mode after an m move", view.mode_name() == "select", view.mode_name())
p = px(0.55, 0.05)
view.send_mouse_move_event(p, 0)
view.send_mouse_press_event(p, L)
view.send_mouse_release_event(p, L)
view.send_mouse_move_event(px(-0.15, 0.3), 0)
view.send_mouse_move_event(px(-0.1, 0.25), 0)
check("a later click does not pick the shape up", m2_box() == moved and "SizeAllCursor" not in canvas_cursor(),
      (str(m2_box()), canvas_cursor()))

check("m is bound to the OpenLayout move", mw.get_key_bindings().get("openlayout_menu.move") == "M",
      mw.get_key_bindings().get("openlayout_menu.move"))

print("PASS drag_move" if not failures else f"FAIL drag_move: {', '.join(failures)}")
