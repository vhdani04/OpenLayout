# A pin and its label move together: selecting the pin shape selects its label, a label selected on
# its own moves alone. KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_pin_group.py
# Mouse input goes through LayoutView.send_mouse_* - the same dispatch as real mouse events.
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import gui, mirror  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)

gds = Path(tempfile.mkdtemp()) / "p.gds"
ly = pya.Layout()
ly.dbu = 0.00025
top = ly.create_cell("TOP")
pin, lab, drw = ly.layer(19, 251), ly.layer(19, 2), ly.layer(19, 0)
top.shapes(pin).insert(pya.DBox(0.0, 0.0, 0.2, 0.04))                # pin A, its label on the pin purpose
top.shapes(pin).insert(pya.DText("A", pya.DTrans(0.1, 0.02)))
top.shapes(pin).insert(pya.DBox(0.0, 0.2, 0.2, 0.24))                # pin B, its label on the label purpose
top.shapes(lab).insert(pya.DText("B", pya.DTrans(0.1, 0.22)))
top.shapes(drw).insert(pya.DBox(0.4, 0.0, 0.6, 0.04))                # a wire with a label: not a pin
top.shapes(drw).insert(pya.DText("W", pya.DTrans(0.5, 0.02)))
top.shapes(pin).insert(pya.DText("FAR", pya.DTrans(0.1, 0.12)))      # a label off every pin
ly.write(str(gds))

mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.max_hier()
view.zoom_box(pya.DBox(-0.2, -0.2, 0.8, 0.5))
view.switch_mode("select")
cell = view.active_cellview().cell
layout = view.active_cellview().layout()
pin, lab, drw = layout.layer(19, 251), layout.layer(19, 2), layout.layer(19, 0)
L = pya.ButtonState.LeftButton


def px(x, y):
    """micrometers -> widget pixels (y down)"""
    q = view.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, view.viewport_height() - q.y)


def click(x, y):
    q = px(x, y)
    view.send_mouse_move_event(q, 0)
    view.send_mouse_press_event(q, L)
    view.send_mouse_release_event(q, L)


def drag(a, b, steps=6):
    """press, move with the button down, release, then move the mouse away"""
    pa, pb = px(*a), px(*b)
    view.send_mouse_move_event(pa, 0)
    view.send_mouse_press_event(pa, L)
    for i in range(1, steps + 1):
        view.send_mouse_move_event(pa + (pb - pa) * (i / steps), L)
    view.send_mouse_release_event(pb, L)
    view.send_mouse_move_event(pb + pya.DVector(40, 40), 0)


def selected():
    """sorted descriptions of the selection: box@left,bottom or text@x,y"""
    out = []
    for o in view.each_object_selected():
        s = o.shape
        out.append(f"text {s.text_string}" if s.is_text() else f"box {layout.get_info(o.layer).datatype}")
    return sorted(out)


def text_at(name):
    for li in (pin, lab, drw):
        for s in cell.shapes(li).each(pya.Shapes.STexts):
            if s.text_string == name:
                t = s.dtext
                return round(t.x, 4), round(t.y, 4)


def box_at(li, y):
    for s in cell.shapes(li).each(pya.Shapes.SBoxes):
        b = s.dbbox()
        if abs(b.bottom - y) < 0.06:
            return round(b.left, 4), round(b.bottom, 4)


# 1. a click on the pin shape (away from its label) selects the label with it
view.clear_selection()
click(0.02, 0.02)
check("clicking a pin shape selects its label too", selected() == ["box 251", "text A"], selected())

# 2. dragging it takes the label along
drag((0.02, 0.02), (0.02, -0.08))
check("the dragged pin's label moves with it", box_at(pin, -0.1) == (0.0, -0.1) and text_at("A") == (0.1, -0.08),
      (box_at(pin, -0.1), text_at("A")))

# 3. a label on the label purpose belongs to its pin too; mirroring the pin takes it along
view.clear_selection()
click(0.02, 0.22)
check("a label-purpose label is selected with its pin", selected() == ["box 251", "text B"], selected())
mirror.transform(view, "mirror_y")
check("mirroring the pin keeps its label on it", text_at("B") == (0.1, 0.22), text_at("B"))

# 4. a label selected on its own moves alone
view.clear_selection()
p = pya.ObjectInstPath()
p.cv_index = 0
p.top = cell.cell_index()
p.layer = pin
p.shape = next(s for s in cell.shapes(pin).each(pya.Shapes.STexts) if s.text_string == "A")
view.object_selection = [p]
check("a label selected alone stays alone", selected() == ["text A"], selected())
drag((0.1, -0.08), (0.3, -0.08))
check("... and moves by itself", abs(text_at("A")[0] - 0.3) < 0.005 and box_at(pin, -0.1) == (0.0, -0.1),
      (text_at("A"), box_at(pin, -0.1)))

# 5. not pins: a wire's label, a label off every pin
view.clear_selection()
click(0.42, 0.02)
check("a wire (drawing purpose) does not take its label", selected() == ["box 0"], selected())
view.clear_selection()
click(0.18, 0.22)
check("only the labels on the pin come along", "text FAR" not in selected(), selected())

# 6. undo: the drag of pin + label is one step
view.clear_selection()
before = (box_at(pin, 0.2), text_at("B"))
click(0.02, 0.22)
drag((0.02, 0.22), (0.02, 0.32))
moved = (box_at(pin, 0.3), text_at("B"))
mw.cm_undo()
check("one undo puts pin and label back", (box_at(pin, 0.2), text_at("B")) == before, (moved, before))

print("PASS pin_group" if not failures else f"FAIL pin_group: {', '.join(failures)}")
