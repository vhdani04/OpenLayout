# Custom standard cells in the editor (frame command, chaining on drop, Chain Selected), run in
# KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_stdcell_gui.py
# Mouse input goes through LayoutView.send_mouse_* - the same dispatch as real mouse events.
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import axes, gui, stdcell  # noqa: E402
from openlayout_kl.asap7 import LAYERS  # noqa: E402
from openlayout_kl.pcells import LIBRARY  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)

gds = Path(tempfile.mkdtemp()) / "c.gds"
ly = pya.Layout()
ly.dbu = 0.00025
ly.technology_name = "asap7"
top = ly.create_cell("CELL")
for kind, x in (("nmos", 0), ("nmos", 0.162), ("pmos", 0), ("pmos", 0.5)):
    pc = ly.create_cell(kind, LIBRARY, {"row": True, "nfin": 2, "nf": 1})
    top.insert(pya.DCellInstArray(pc.cell_index(), pya.DTrans(x, 0)))
ly.write(str(gds))

mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.max_hier()
view.zoom_box(pya.DBox(-0.1, -0.1, 0.8, 0.4))
view.switch_mode("select")
cell = view.active_cellview().cell
L = pya.ButtonState.LeftButton

# frame: drawn at the origin as plain shapes, wide enough for the devices; again it is redrawn
stdcell.insert_frame(view)
check("the frame covers the devices", stdcell.frame_params(cell) == {"cpp": 13, "vt": "rvt"}
      and cell.child_instances() == 4, (stdcell.frame_params(cell), cell.child_instances()))
stdcell.insert_frame(view, cpp=14, vt="lvt")
pins = [s.text_string for s in cell.shapes(cell.layout().layer(LAYERS["m1"], 251)).each(pya.Shapes.STexts)]
bound = cell.layout().find_layer(LAYERS["boundary"], 0)
check("asked again, the frame is redrawn (one boundary, one pin per rail)",
      stdcell.frame_params(cell) == {"cpp": 14, "vt": "lvt"} and cell.shapes(bound).size() == 1
      and sorted(pins) == ["VDD", "VSS"], (stdcell.frame_params(cell), pins))


def frame_boxes():
    return sorted(str(s.dbbox()) for s in stdcell.frame_shapes(cell))


def px(x, y):
    q = view.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, view.viewport_height() - q.y)


def drag(a, b, steps=6):
    pa, pb = px(*a), px(*b)
    view.send_mouse_move_event(pa, 0)
    view.send_mouse_press_event(pa, L)
    for i in range(1, steps + 1):
        view.send_mouse_move_event(pa + (pb - pa) * (i / steps), L)
    view.send_mouse_release_event(pb, L)
    view.send_mouse_move_event(pb + pya.DVector(40, 40), 0)


def click_at(x, y):
    q = px(x, y)
    view.send_mouse_move_event(q, 0)
    view.send_mouse_press_event(q, L)
    view.send_mouse_release_event(q, L)


def carry(a, b, steps=5):
    """with the object at a selected: drag it to b"""
    drag(a, b, steps)


def move(a, b):
    """click to select, then drag it"""
    view.clear_selection()
    click_at(*a)
    carry(a, b)


def devs(kind):
    out = []
    for i in cell.each_inst():
        if i.is_pcell() and i.pcell_declaration().name() == kind:
            p = i.pcell_parameters_by_name()
            out.append((round(i.dcplx_trans.disp.x * 1000), bool(p["abut_left"]), bool(p["abut_right"])))
    return sorted(out)


# drop the second nMOS a little further left (still with both dummy gates): it snaps into the chain
move((0.27, 0.05), (0.26, 0.05))
check("a transistor dropped next to another chains (shared diffusion)", devs("nmos") == [(0, False, True), (54, True, False)],
      devs("nmos"))
check("still in Select mode after the drop", view.mode_name() == "select", view.mode_name())

# a drag on empty space inside the frame selects; it does not move the frame
fb = frame_boxes()
drag((0.7, 0.2), (0.74, 0.24))
check("dragging empty space in the frame does not move it", frame_boxes() == fb)


def click_at(x, y):
    q = px(x, y)
    view.send_mouse_move_event(q, 0)
    view.send_mouse_press_event(q, L)
    view.send_mouse_release_event(q, L)


click_at(0.1, 0.05)
sel = list(view.each_object_selected())
check("a click on a transistor selects the transistor, not the frame under it",
      len(sel) == 1 and sel[0].is_cell_inst() and sel[0].inst().pcell_declaration().name() == "nmos",
      [o.is_cell_inst() for o in sel])

# a frame shape is selected by a click on empty space; selected, it drags; a transistor under the
# press still moves on its own
view.clear_selection()
click_at(0.7, 0.2)
check("a click on empty space in the cell selects a frame shape", stdcell.is_frame_selection(view))
nmos_before = devs("nmos")
click_at(0.17, 0.05)                                # on the chained nMOS: selects it, not the frame
check("with a frame shape selected, a click on a transistor selects the transistor",
      [o.inst().pcell_declaration().name() for o in view.each_object_selected() if o.is_cell_inst()] == ["nmos"])
carry((0.17, 0.05), (0.37, 0.05))
check("... which then moves, not the frame", frame_boxes() == fb and devs("nmos") != nmos_before,
      (devs("nmos"), nmos_before))
mw.cm_undo()
view.clear_selection()
click_at(0.7, 0.2)
picked = [str(o.shape.dbbox()) for o in view.each_object_selected()]
carry((0.7, 0.2), (0.7 + 0.108, 0.2))
moved = [b for b in frame_boxes() if b not in fb]
check("a selected frame shape moves like any shape", len(picked) == 1 and len(moved) == 1, (picked, moved))
mw.cm_undo()

# Chain Selected: the two pMOS, far apart
view.clear_selection()
click_at(0.1, 0.2)                                   # click, then Shift+click: like the mouse
q = px(0.6, 0.2)
view.send_mouse_move_event(q, 0)
view.send_mouse_press_event(q, L | pya.ButtonState.ShiftKey)
view.send_mouse_release_event(q, L | pya.ButtonState.ShiftKey)
check("Shift+click adds the transistor, not the frame under it",
      [o.inst().pcell_declaration().name() for o in view.each_object_selected() if o.is_cell_inst()] == ["pmos", "pmos"]
      and not any(stdcell.is_frame_object(o) for o in view.each_object_selected()))
gui.instance.chain_selected()
check("Chain Selected chains the selected transistors", devs("pmos") == [(0, False, True), (54, True, False)],
      devs("pmos"))
check("the selection is still usable after chaining", view.has_object_selection() and view.selection_bbox().width() > 0)

mw.cm_undo()
check("chaining is one undo step", devs("pmos") == [(0, False, False), (500, False, False)], devs("pmos"))

# the menu command's dialogs, answered by stand-ins with KLayout's real signatures
class Dialogs:
    asked = []

    @staticmethod
    def ask_int_ex(title, label, value, vmin, vmax, step):
        Dialogs.asked.append(("width", value))
        return 9

    @staticmethod
    def ask_item(title, label, items, index):
        Dialogs.asked.append(("vt", items[index]))
        return "slvt"


real_dialog, pya.InputDialog = pya.InputDialog, Dialogs
try:
    gui.instance.frame_dialog()
finally:
    pya.InputDialog = real_dialog
p = stdcell.frame_params(cell)
check("the Standard-Cell Frame menu command asks width and VT and applies them",
      p == {"cpp": 9, "vt": "slvt"} and Dialogs.asked == [("width", 14), ("vt", "lvt")], (p, Dialogs.asked))

# the x / y axes through the origin, switchable from the OpenLayout menu
live = [a for a in axes._all if not a.destroyed()]
lines = sorted(str(e) for a in live for e in a.lines)
check("the view shows the x and y axes through the origin", len(live) >= 1
      and "(-100000,0;100000,0)" in lines and "(0,-100000;0,100000)" in lines, lines)
toggle = mw.menu().action("openlayout_menu.axes")
toggle.trigger()
check("Show Axes switches them off", not axes.visible() and not any(a.markers for a in live))
toggle.trigger()
check("and on again", axes.visible() and all(len(a.markers) == 2 for a in live))

print("PASS stdcell_gui" if not failures else f"FAIL stdcell_gui: {', '.join(failures)}")
