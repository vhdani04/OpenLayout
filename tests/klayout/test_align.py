# Align (key A), run in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_align.py
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
check("a is bound to align", mw.get_key_bindings().get("openlayout_menu.align") == "A",
      mw.get_key_bindings().get("openlayout_menu.align"))

gds = Path(tempfile.mkdtemp()) / "a.gds"
ly = pya.Layout()
ly.dbu = 0.00025
top = ly.create_cell("TOP")
sub = ly.create_cell("SUB")
sub.shapes(ly.layer(19, 0)).insert(pya.DBox(0, 0, 0.1, 0.1))                 # M1 in a sub cell
sub.shapes(ly.layer(20, 0)).insert(pya.DBox(0.02, 0.03, 0.06, 0.07))          # an inner M2 shape
top.insert(pya.DCellInstArray(sub.cell_index(), pya.DTrans(pya.DTrans.M0, 0, 0.1)))  # mirrored: same 0..0.1 box
top.shapes(ly.layer(20, 0)).insert(pya.DBox(0.3, 0.2, 0.4, 0.3))               # M2 box B
ly.write(str(gds))

mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.max_hier()
view.zoom_box(pya.DBox(-0.1, -0.15, 0.55, 0.4))
view.switch_mode("select")
cell = view.active_cellview().cell
L, R = pya.ButtonState.LeftButton, pya.ButtonState.RightButton
align = mw.menu().action("openlayout_menu.align")


def px(x, y):
    """micrometers -> widget pixels (y down)"""
    q = view.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, view.viewport_height() - q.y)


def hover(x, y):
    view.send_mouse_move_event(px(x, y), 0)


def click(x, y, b=L):
    p = px(x, y)
    view.send_mouse_move_event(p, 0)
    view.send_mouse_press_event(p, b)
    view.send_mouse_release_event(p, b)


def inst_pos():
    return [i.dcplx_trans.disp for i in cell.each_inst()][0]


def b_box():
    return [s.dbbox() for s in cell.shapes(ly.layer(20, 0)).each()][0]


# instance: its right edge (x = 0.1) to B's left edge (x = 0.3)
click(0.05, 0.05)                    # select the instance
hover(0.1, 0.05)
align.trigger()
click(0.1, 0.05)                     # reference: the instance's right edge
click(0.3, 0.25)                     # target: B's left edge
d = inst_pos()
check("align moves the instance sideways onto the target edge", abs(d.x - 0.2) < 1e-6 and abs(d.y - 0.1) < 1e-6, d)
check("the aligned object stays selected", view.has_object_selection())

# box B: its bottom edge to the top of the inner M2 shape of the moved instance (y = 0.07)
view.clear_selection()
hover(0.35, 0.2)
align.trigger()                      # nothing selected: takes the object under the mouse
click(0.35, 0.2)                     # reference: B's bottom edge
click(0.24, 0.07)                    # target: top edge of the inner M2 (0.22..0.26 x 0.03..0.07)
b = b_box()
check("align picks edges inside instances, moves only up/down for horizontal edges",
      abs(b.bottom - 0.07) < 1e-6 and abs(b.left - 0.3) < 1e-6, b)

mw.cm_undo()
check("an align is one undo step", abs(b_box().bottom - 0.2) < 1e-6, b_box())

# a target edge of the wrong direction is not taken; Esc cancels
view.clear_selection()
hover(0.35, 0.2)
align.trigger()
click(0.35, 0.2)                     # horizontal reference
click(0.2, 0.05)                     # vertical edge only (instance left edge): ignored
check("a perpendicular target edge is ignored", abs(b_box().bottom - 0.2) < 1e-6, b_box())
mw.menu().action("edit_menu.cancel").trigger()
click(0.3, 0.1)                      # would be a valid target if align were still running
check("Esc cancels align", abs(b_box().bottom - 0.2) < 1e-6, b_box())

# right click cancels too
click(0.35, 0.25)
align.trigger()
click(0.35, 0.3)
click(0.5, 0.0, R)
click(0.24, 0.07)
check("right click cancels align", abs(b_box().top - 0.3) < 1e-6, b_box())

print("PASS align" if not failures else f"FAIL align: {', '.join(failures)}")
