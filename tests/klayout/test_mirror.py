# Mirror / rotate the selection (the right-click menu): shapes and PCell instances, about the
# selection's centre or the cell origin, undo, and the right click itself. KLayout with a main
# window (headless):
#   klayout -e -z -nc -r tests/klayout/test_mirror.py
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

gds = Path(tempfile.mkdtemp()) / "m.gds"
ly = pya.Layout()
ly.dbu = 0.00025
ly.technology_name = "asap7"                          # the PCell library belongs to the asap7 technology
top = ly.create_cell("TOP")
ell = pya.DPolygon([pya.DPoint(0.3, 0), pya.DPoint(0.5, 0), pya.DPoint(0.5, 0.05), pya.DPoint(0.35, 0.05),
                    pya.DPoint(0.35, 0.2), pya.DPoint(0.3, 0.2)])          # an L: asymmetric both ways
top.shapes(ly.layer(19, 0)).insert(ell)
nmos = ly.create_cell("nmos", "OpenLayout_ASAP7", {"nfin": 2, "nf": 1})
top.insert(pya.DCellInstArray(nmos.cell_index(), pya.DTrans(pya.DVector(-0.4, 0))))
ly.write(str(gds))

mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.max_hier()
view.zoom_box(pya.DBox(-0.6, -0.3, 0.7, 0.4))
view.switch_mode("select")
cell = view.active_cellview().cell
layout = view.active_cellview().layout()
m1 = layout.layer(19, 0)


def poly():
    return next(iter(cell.shapes(m1).each())).dpolygon


def inst():
    return next(iter(cell.each_inst()))


def select_shape():
    view.object_selection = []
    p = pya.ObjectInstPath()
    p.top = cell.cell_index()
    p.layer = m1
    p.shape = next(iter(cell.shapes(m1).each()))
    view.object_selection = [p]


def select_inst():
    view.object_selection = []
    p = pya.ObjectInstPath()
    p.top = cell.cell_index()
    p.append_path(pya.InstElement.new(inst()))
    view.object_selection = [p]


def same(a, b):
    return sorted(str(pt) for pt in a.each_point_hull()) == sorted(str(pt) for pt in b.each_point_hull())


# 1. a shape, about its own centre: flipped in place
before = poly()
bb = before.bbox()
select_shape()
check("mirror over X: one object", mirror.transform(view, "mirror_x") == 1)
after = poly()
want = before.transformed(mirror.about(mirror.OPS["mirror_x"][1], bb.center()))
check("mirror over X: flipped top to bottom in place", same(after, want) and after.bbox() == bb, str(after))

# 2. undo restores it
mw.cm_undo()
check("undo restores the shape", same(poly(), before), str(poly()))

# 3. about the cell origin: over the Y axis lands at negative x
select_shape()
mirror.transform(view, "mirror_y", origin=True)
check("mirror over the cell Y axis: x -> -x", poly().bbox() == pya.DBox(-0.5, 0, -0.3, 0.2), str(poly().bbox()))
mw.cm_undo()

# 4. a PCell instance: mirrored and rotated in place
ib = inst().dbbox()
select_inst()
mirror.transform(view, "mirror_x")
check("instance mirror over X: mirrored, same place", inst().is_mirror() if hasattr(inst(), "is_mirror")
      else inst().dcplx_trans.is_mirror(), str(inst().dcplx_trans))
check("instance mirror over X: same bounding box", inst().dbbox() == ib, f"{inst().dbbox()} vs {ib}")
select_inst()
mirror.transform(view, "rot_ccw")
nb = inst().dbbox()
check("instance rotate: turned about its centre",
      abs(nb.width() - ib.height()) < 1e-6 and abs(nb.center().distance(ib.center())) < 0.001, f"{nb} vs {ib}")

# 5. the right click: selects what is under the mouse, then opens the menu. The real popup is
#    exercised through a menu whose exec_ returns at once (a real one waits for the user).
check("the menu pops up at a screen position", isinstance(mirror.cursor_pos(), pya.QPoint), repr(mirror.cursor_pos()))
popped = []
real_build = mirror.build_menu


class NoWaitMenu:
    def __init__(self, menu):
        self.menu = menu

    def exec_(self, pos):
        popped.append((pos.x, pos.y))


mirror.build_menu = lambda v, parent=None: NoWaitMenu(real_build(v, parent))
select_shape()
mirror.show_menu(view)
check("show_menu runs the popup at the cursor", len(popped) == 1, str(popped))
mirror.build_menu = real_build

shown = []
mirror.show_menu = lambda v: shown.append([o.is_cell_inst() for o in v.each_object_selected()])
view.object_selection = []


def px(x, y):
    q = view.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, view.viewport_height() - q.y)


R = pya.ButtonState.RightButton
q = px(0.32, 0.15)                                    # on the L's vertical arm
view.send_mouse_move_event(q, 0)
view.send_mouse_press_event(q, R)
view.send_mouse_release_event(q, R)
check("right click on a shape: selected, menu shown", shown == [[False]], str(shown))
select_inst()
view.send_mouse_move_event(q, 0)
view.send_mouse_press_event(q, R)
view.send_mouse_release_event(q, R)
check("right click with a selection: the menu is for it", shown[-1:] == [[True]], str(shown))

# 6. the menu
menu = mirror.build_menu(view)
texts = [a.text for a in menu.actions()]
check("menu: mirrors, the origin submenu, rotations",
      texts[:3] == [mirror.OPS[k][0] for k in mirror.MIRRORS] and "About the cell origin" in texts
      and mirror.OPS["rot_ccw"][0] in texts, str(texts))

# 7. two chained row transistors: flipping one top to bottom unchains both (their dummy gates come
#    back), in the mirror's own undo step
from openlayout_kl import chain  # noqa: E402

rn = layout.create_cell("nmos", "OpenLayout_ASAP7", {"row": True, "nfin": 2, "nf": 1})
pair = [cell.insert(pya.DCellInstArray(rn.cell_index(), pya.DTrans(pya.DVector(x, 2.0)))) for x in (2.0, 2.054)]
chain.update(cell, moved=[], conn=None)


def pair_flags():
    devs = sorted((i for i in cell.each_inst() if abs(i.dcplx_trans.disp.y - 2.0) < 0.3),
                  key=lambda i: i.dbbox().left)
    return [(i.pcell_parameters_by_name()["abut_left"], i.pcell_parameters_by_name()["abut_right"]) for i in devs]


check("two row transistors side by side are chained", pair_flags() == [(False, True), (True, False)], str(pair_flags()))
second = sorted((i for i in cell.each_inst() if abs(i.dcplx_trans.disp.y - 2.0) < 0.01), key=lambda i: i.dbbox().left)[1]
p = pya.ObjectInstPath()
p.top = cell.cell_index()
p.append_path(pya.InstElement.new(second))
view.object_selection = [p]
mirror.transform(view, "mirror_x")
check("flipping one top to bottom unchains both", pair_flags() == [(False, False), (False, False)], str(pair_flags()))
mw.cm_undo()
check("one undo restores the flip and the chain", pair_flags() == [(False, True), (True, False)], str(pair_flags()))

print("PASS mirror" if not failures else f"FAIL mirror: {', '.join(failures)}")
