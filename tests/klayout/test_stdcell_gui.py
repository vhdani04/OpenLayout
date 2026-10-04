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

from openlayout_kl import gui, stdcell  # noqa: E402
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

# frame: inserted at the origin, wide enough for the devices; asked again it resizes, no duplicates
frame = stdcell.insert_frame(view)
check("the frame covers the devices", frame.pcell_parameters_by_name()["cpp"] == 13
      and abs(frame.dbbox().top - 0.27 - 0.022) < 1e-6, frame.pcell_parameters_by_name())
stdcell.insert_frame(view, cpp=14, vt="lvt")
frames = [i for i in cell.each_inst() if stdcell._is_frame(i)]
pins = [s.text_string for s in cell.shapes(cell.layout().layer(LAYERS["m1"], 251)).each(pya.Shapes.STexts)]
check("asked again, the frame is resized (one frame, one pin per rail)",
      len(frames) == 1 and frames[0].pcell_parameters_by_name()["cpp"] == 14 and sorted(pins) == ["VDD", "VSS"],
      (len(frames), pins))


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


def devs(kind):
    out = []
    for i in cell.each_inst():
        if i.is_pcell() and i.pcell_declaration().name() == kind:
            p = i.pcell_parameters_by_name()
            out.append((round(i.dcplx_trans.disp.x * 1000), bool(p["abut_left"]), bool(p["abut_right"])))
    return sorted(out)


# drop the second nMOS a little further left (still with both dummy gates): it snaps into the chain
drag((0.27, 0.05), (0.26, 0.05))
check("a transistor dropped next to another chains (shared diffusion)", devs("nmos") == [(0, False, True), (54, True, False)],
      devs("nmos"))
check("still in Select mode after the drop", view.mode_name() == "select", view.mode_name())

# a drag on empty space inside the frame selects; it does not move the frame
fb = frames[0].dbbox()
drag((0.7, 0.2), (0.74, 0.24))
check("dragging empty space in the frame does not move it", cell.each_inst() and
      [i for i in cell.each_inst() if stdcell._is_frame(i)][0].dbbox() == fb)

# a selected frame drags (click it first); a transistor under the press still moves on its own
view.clear_selection()
click = px(0.7, 0.2)
view.send_mouse_move_event(click, 0)
view.send_mouse_press_event(click, L)
view.send_mouse_release_event(click, L)
check("a click on empty space in the cell selects the frame", stdcell.is_frame_selection(view))
nmos_before = devs("nmos")
drag((0.17, 0.05), (0.37, 0.05))                    # on the chained nMOS: moves that one, not the frame
check("with the frame selected, dragging a transistor moves the transistor",
      [i for i in cell.each_inst() if stdcell._is_frame(i)][0].dbbox() == fb and devs("nmos") != nmos_before,
      (devs("nmos"), nmos_before))
mw.cm_undo()
view.clear_selection()
view.send_mouse_move_event(click, 0)
view.send_mouse_press_event(click, L)
view.send_mouse_release_event(click, L)
drag((0.7, 0.2), (0.7 + 0.108, 0.2))
nfb = [i for i in cell.each_inst() if stdcell._is_frame(i)][0].dbbox()
check("a selected frame drags", abs(nfb.left - fb.left - 0.108) < 1e-6 and nfb.bottom == fb.bottom, (str(fb), str(nfb)))
mw.cm_undo()

# Chain Selected: the two pMOS, far apart
view.clear_selection()
for x in (0.1, 0.6):
    view.select_from(pya.DPoint(x, 0.2), pya.LayoutView.SelectionMode.Add)
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
frames = [i for i in cell.each_inst() if stdcell._is_frame(i)]
p = frames[0].pcell_parameters_by_name()
check("the Standard-Cell Frame menu command asks width and VT and applies them",
      len(frames) == 1 and (p["cpp"], p["vt"]) == (9, "slvt") and Dialogs.asked == [("width", 14), ("vt", "lvt")],
      (p, Dialogs.asked))

print("PASS stdcell_gui" if not failures else f"FAIL stdcell_gui: {', '.join(failures)}")
