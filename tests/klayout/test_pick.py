# Picking in Select mode: the hover highlight shows what a click selects, also where the
# standard-cell frame lies under the shapes (a wire on a transistor takes the wire, not the frame
# fin or the transistor). KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_pick.py
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.environ["OPENLAYOUT_HOME"] + "/klayout/python")
import pya
from openlayout_kl import gui, stdcell, drag_move

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
    h, c = hover_click(x, y, clear=False)
    check(f"{name} (clicked again): still the same", [e for e in h if e != "(ours)"] == c, f"hover {h}, click {c}")
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
print("PASS pick" if not failures else f"FAIL pick: {', '.join(failures)}")
