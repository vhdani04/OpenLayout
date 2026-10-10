# Picking in Select mode: the hover highlight shows what a click selects, also where the
# standard-cell frame lies under the shapes (a wire on a transistor takes the wire, not the frame
# fin or the transistor). KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_pick.py
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.environ["OPENLAYOUT_HOME"] + "/klayout/python")
import pya
from openlayout_kl import gui, stdcell, drag_move, picking

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)
gds = Path(tempfile.mkdtemp()) / "s.gds"
ly = pya.Layout(); ly.dbu = 0.00025; ly.technology_name = "asap7"
top = ly.create_cell("TOP")
stdcell.draw_frame(top, 4)
top.shapes(ly.layer(19, 0)).insert(pya.DBox(0.05, 0.08, 0.17, 0.098))      # M1 wire
top.shapes(ly.layer(17, 0)).insert(pya.DBox(0.098, 0.03, 0.122, 0.12))      # LISD crossing it
top.shapes(ly.layer(16, 0)).insert(pya.DBox(0.13, 0.07, 0.16, 0.11))        # LIG pad under M1
from openlayout_kl.pcells import LIBRARY
pc = ly.create_cell("nmos", LIBRARY, {"nfin": 2, "nf": 1, "row": True})
top.insert(pya.DCellInstArray(pc.cell_index(), pya.DTrans(pya.DVector(0.054, 0))))
top.shapes(ly.layer(19, 0)).insert(pya.DBox(0.09, 0.035, 0.13, 0.053))      # M1 over the transistor
ly.write(str(gds))
mw.resize(1400, 900); mw.show()
mw.load_layout(str(gds), "asap7", 1)
v = mw.current_view()
for _ in range(20): pya.Application.instance().process_events()
v.max_hier(); v.zoom_box(pya.DBox(0.0, 0.0, 0.216, 0.15)); v.switch_mode("select")
L = pya.ButtonState.LeftButton

def px(x, y):
    q = v.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, v.viewport_height() - q.y)

def desc(objs):
    out = []
    for o in objs:
        if o.is_cell_inst(): out.append("inst")
        else:
            info = o.layout().get_info(o.layer) if hasattr(o, "layout") else v.cellview(o.cv_index).layout().get_info(o.layer)
            out.append(f"{info.layer}/{info.datatype}{'(frame)' if stdcell.is_frame_object(o) else ''}")
    return out

import time
def hover_click(x, y, clear=True):
    if clear:
        v.object_selection = []
    for k in range(3):
        v.send_mouse_move_event(px(x, y) + pya.DVector(k * 2, 0), 0)
    for _ in range(40):
        pya.Application.instance().process_events(); time.sleep(0.02)
    h = desc(v.each_object_selected_transient())
    svc = drag_move._under_mouse[0] if drag_move._under_mouse else None
    if svc is not None and svc.hover_target is not None:
        h = desc([svc.hover_target]) + ["(ours)"]
    q = px(x, y)
    v.send_mouse_press_event(q, L); v.send_mouse_release_event(q, L)
    for _ in range(5):
        pya.Application.instance().process_events()
    return h, desc(v.each_object_selected())

for name, (x, y) in {"M1 over transistor": (0.11, 0.044), "transistor only": (0.081, 0.06)}.items():
    h, c = hover_click(x, y)
    check(f"{name}: the hover shows what the click takes", [e for e in h if e != "(ours)"] == c, f"hover {h}, click {c}")
    nxt = desc(picking.candidates(v, v.viewport_trans().inverted() * pya.DPoint(px(x, y).x, v.viewport_height() - px(x, y).y))[1:2])
    h, c2 = hover_click(x, y, clear=False)
    check(f"{name} (clicked again): the next object under the mouse", c2 == nxt and c2 != c, f"{c} -> {c2}, next {nxt}")
for name, (x, y) in {"M1 only": (0.07, 0.089), "M1 over LISD": (0.11, 0.089), "M1 over LIG": (0.145, 0.089),
                     "LIG only": (0.145, 0.105)}.items():
    v.object_selection = []
    for k in range(3):
        q = px(x, y)
        v.send_mouse_move_event(q + pya.DVector(k * 2, 0), 0)
        pya.Application.instance().process_events()
    import time
    for _ in range(40):
        pya.Application.instance().process_events(); time.sleep(0.02)
    q = px(x, y)
    hover = desc(v.each_object_selected_transient())
    v.send_mouse_press_event(q, L); v.send_mouse_release_event(q, L)
    sel = desc(v.each_object_selected())
    check(f"{name}: the hover shows what the click takes", hover == sel, f"hover {hover}, click {sel}")

h, c = hover_click(0.11, 0.044)
check("a wire on a transistor: the wire, not the frame fin or the transistor", c == ["19/0"], str(c))

# the frame's GCUT over the bottom rail, under the transistor's gate: clicking again goes down to it
v.object_selection = []
GC = (0.081, 0.019)          # above the first fin, inside the rail's GCUT
seq = []
for k in range(3):
    h, c = hover_click(*GC, clear=(k == 0))
    seq.append(c)
check("clicking again cycles down to the GCUT under the transistor", seq[0] == ["inst"] and seq[1] == ["10/0(frame)"],
      str(seq))

# Instances selectable off: the click (and the hover) take the shapes under the transistor
picking.types["instance"] = False
h, c = hover_click(0.081, 0.06)
check("instances off: a click takes the shape under the transistor, not the transistor", c and c != ["inst"], f"{h} {c}")
check("instances off: the hover shows the same", [e for e in h if e != "(ours)"] == c, f"hover {h}, click {c}")
h, c = hover_click(*GC)
check("instances off: the GCUT under the gate in one click", c == ["10/0(frame)"], str(c))

# only GCUT selectable (NS with GCUT current) - a click elsewhere takes nothing
picking.locked.update((info.layer, info.datatype) for info in ly.layer_infos() if (info.layer, info.datatype) != (10, 0))
h, c = hover_click(*GC)
check("only GCUT selectable: a click there takes the GCUT", c == ["10/0(frame)"], str(c))
h, c = hover_click(0.07, 0.089)
check("only GCUT selectable: a click on a wire takes nothing", c == [], str(c))
picking.locked.clear()
picking.types["instance"] = True
h, c = hover_click(0.07, 0.089)
check("all selectable again: the wire", c == ["19/0"], str(c))


# a box selection leaves out what cannot be selected (a locked layer, a type switched off)
def box_select(a, b):
    v.object_selection = []
    pa, pb = px(*a), px(*b)
    v.send_mouse_move_event(pa, 0)
    v.send_mouse_press_event(pa, L)
    for i in range(1, 7):
        v.send_mouse_move_event(pa + (pb - pa) * (i / 6), L)
    v.send_mouse_release_event(pb, L)
    for _ in range(5):
        pya.Application.instance().process_events()
    return desc(v.each_object_selected())


everything = box_select((-0.02, -0.03), (0.24, 0.3))
picking.locked.add((19, 0))
picking.types["frame"] = picking.types["boundary"] = False
boxed = box_select((-0.02, -0.03), (0.24, 0.3))
check("a box selection skips locked layers and switched-off types",
      "19/0" in everything and boxed and not any(d.startswith("19/0") or "(frame)" in d for d in boxed),
      f"{sorted(set(everything))} -> {sorted(set(boxed))}")
picking.select_all_types()

print("PASS pick" if not failures else f"FAIL pick: {', '.join(failures)}")
