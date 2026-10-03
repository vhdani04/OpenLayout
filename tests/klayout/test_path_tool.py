# Path tool behaviour, run in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_path_tool.py
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl.path_tool import PathTool  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


gds = Path(tempfile.mkdtemp()) / "p.gds"
ly = pya.Layout()
ly.dbu = 0.00025
top = ly.create_cell("TOP")
m1 = ly.layer(19, 0)
top.shapes(m1).insert(pya.DBox(0, 0, 0.2, 0.036))      # an M1 wire, 36 nm wide, ending at x = 0.2
ly.write(str(gds))

mw = pya.Application.instance().main_window()
mw.resize(1400, 900)  # a real screen-sized canvas: snapping ranges are in pixels
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.zoom_box(pya.DBox(-0.1, -0.2, 0.6, 0.3))
it = view.begin_layers()
while not it.at_end():
    if it.current().source_layer == 19 and it.current().source_datatype == 0 and not it.current().has_children():
        view.current_layer = it
        break
    it.next()

tool = PathTool(view)
L = pya.ButtonState.LeftButton
cell = view.active_cellview().cell
before = cell.shapes(m1).size()

# continue the wire from its right edge, then go off-axis: must stay Manhattan
tool.mouse_click_event(pya.DPoint(0.2005, 0.02), L, True)
check("edge picked: width = edge length", abs(tool.width - 0.036) < 1e-6, tool.width)
check("starts flush at edge midpoint", tool.points[0] == pya.DPoint(0.2, 0.018) and tool.bgn_ext == 0,
      (str(tool.points[0]), tool.bgn_ext))
tool.mouse_click_event(pya.DPoint(0.4, 0.05), L, True)   # first segment forced horizontal
tool.mouse_click_event(pya.DPoint(0.43, 0.25), L, True)  # then vertical (larger delta)
tool.mouse_double_click_event(pya.DPoint(0.43, 0.25), L, True)
paths = [s for s in cell.shapes(m1).each() if s.is_path()]
check("one path created", cell.shapes(m1).size() == before + 1 and len(paths) == 1)
if paths:
    p = paths[0].dpath
    pts = list(p.each_point())
    manhattan = all(a.x == b.x or a.y == b.y for a, b in zip(pts, pts[1:]))
    check("path width from edge", abs(p.width - 0.036) < 1e-6, p.width)
    check("segments are horizontal/vertical", manhattan, [str(q) for q in pts])
    check("first segment leaves the edge horizontally", pts[1].y == pts[0].y, [str(q) for q in pts])

# snapping: a second M1 rectangle to the right; a path off A's edge snaps onto B's facing edge
cell.shapes(m1).clear()
cell.shapes(m1).insert(pya.DBox(0, 0, 0.2, 0.036))       # A
cell.shapes(m1).insert(pya.DBox(0.35, -0.02, 0.5, 0.06))  # B, its left edge spans A's wire band
view.zoom_box(pya.DBox(-0.1, -0.2, 0.6, 0.3))
tool.mouse_click_event(pya.DPoint(0.2005, 0.02), L, True)
nxt, edge = tool.next_point(pya.DPoint(0.344, 0.03))
check("end snaps onto the facing edge of the next shape", edge is not None and abs(nxt.x - 0.35) < 1e-9
      and abs(nxt.y - 0.018) < 1e-9, (str(nxt), str(edge)))
tool.mouse_click_event(pya.DPoint(0.344, 0.03), L, True)
tool.key_event(pya.KeyCode.Return, 0)
paths = [s for s in cell.shapes(m1).each() if s.is_path()]
if paths:
    p = paths[0].dpath
    pts = list(p.each_point())
    check("snapped path ends flush on the edge", abs(pts[-1].x - 0.35) < 1e-9 and p.end_ext == 0
          and abs(p.bbox().right - 0.35) < 1e-9, (str(pts[-1]), p.end_ext, p.bbox().right))
else:
    check("snapped path ends flush on the edge", False, "no path")

# vertical segment snapping onto a horizontal edge
cell.shapes(m1).insert(pya.DBox(0.39, 0.2, 0.46, 0.26))   # C above, facing the path started at the middle of B's top edge
tool.mouse_click_event(pya.DPoint(0.4, 0.0605), L, True)   # B's top edge (y=0.06): vertical path upward
nxt, edge = tool.next_point(pya.DPoint(0.425, 0.195))
check("vertical segment snaps to the edge above", edge is not None and abs(nxt.y - 0.2) < 1e-9, str(nxt))
nxt, edge = tool.next_point(pya.DPoint(0.425, 0.12))
print(f"   (snap range {tool.pixels(12) * 1000:.1f} nm at this zoom)")
check("no snap far from edges", edge is None and abs(nxt.y - 0.12) < 1e-6, str(nxt))
tool.key_event(pya.KeyCode.Escape, 0)

# a path started in empty space uses the layer minimum width (M1: 18 nm)
tool.mouse_click_event(pya.DPoint(0.0, -0.1), L, True)
check("default width = layer minimum", abs(tool.width - 0.018) < 1e-6, tool.width)
tool.key_event(pya.KeyCode.Escape, 0)
check("Esc cancels", not tool.points)

print("PASS path_tool" if not failures else f"FAIL path_tool: {', '.join(failures)}")
