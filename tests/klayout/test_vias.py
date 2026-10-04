# Vias (ASAP7 sizes) and Create Via (key O), run in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_vias.py
# Mouse input goes through LayoutView.send_mouse_* - the same dispatch as real mouse events.
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import gui, vias  # noqa: E402
from openlayout_kl.pcells import via_choices, via_geometry  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


# geometry: the tech LEF's default vias
g = via_geometry("m1", "m2")["shapes"]
check("V1 is the LEF's VIA12 (18x18 cut, M1 / M2 pads)",
      g == {"v1": [(-9, -9, 9, 9)], "m1": [(-9, -11, 9, 11)], "m2": [(-14, -9, 14, 9)]}, g)
g = via_geometry("m4", "m5")["shapes"]
check("V4 is 24x24 (VIA45)", g["v4"] == [(-12, -12, 12, 12)], g)
g = via_geometry("m3", "m4")["shapes"]
check("V3 is 18x24 (VIA34)", g["v3"] == [(-9, -12, 9, 12)], g)
g = via_geometry("m1", "m2", rows=2, cols=3)["shapes"]
xs = sorted({c[0] for c in g["v1"]})
check("a 2x3 V1 array: 6 cuts 18 nm apart, centred", len(g["v1"]) == 6 and xs == [-45, -9, 27]
      and g["m2"] == [(-50, -27, 50, 27)], (g["v1"], g["m2"]))
g = via_geometry("lig", "m2")["shapes"]
check("a LIG -> M2 stack is V0 + V1 with an M1 landing", set(g) == {"v0", "v1", "lig", "m1", "m2"}
      and len(g["m1"]) == 2, sorted(g))
titles = [t for t, _ in via_choices()]
check("the menu lists V0 (LISD, LIG) to V8, then the stacks", titles[0].startswith("V0  LISD")
      and titles[1].startswith("V0  LIG") and titles[9].startswith("V8") and titles[10].startswith("Stack"),
      titles[:12])

mw = pya.Application.instance().main_window()
gui.start(mw)
check("o is bound to Create Via", mw.get_key_bindings().get("openlayout_menu.via") == "O",
      mw.get_key_bindings().get("openlayout_menu.via"))

# the real dialog, closed by a timer: it must build and return the choice
timer = pya.QTimer(mw)
timer.interval = 300
timer.singleShot = True


def accept_dialog():
    d = pya.QApplication.activeModalWidget()
    if d is not None:
        d.accept()


timer.timeout = accept_dialog
timer.start()
answer = vias.ask_via(mw, {"layers": "m2-m3", "rows": 2, "cols": 1})
check("the Create Via dialog opens and returns the chosen via",
      answer == {"layers": "m2-m3", "rows": 2, "cols": 1}, answer)

gds = Path(tempfile.mkdtemp()) / "v.gds"
ly = pya.Layout()
ly.dbu = 0.00025
ly.create_cell("TOP")
ly.write(str(gds))
mw.resize(1400, 900)
mw.show()
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(20):
    pya.Application.instance().process_events()
view.zoom_box(pya.DBox(-0.2, -0.2, 0.4, 0.3))
view.switch_mode("select")
cell = view.active_cellview().cell
L, R = pya.ButtonState.LeftButton, pya.ButtonState.RightButton


def px(x, y):
    q = view.viewport_trans() * pya.DPoint(x, y)
    return pya.DPoint(q.x, view.viewport_height() - q.y)


def click(x, y, b=L):
    p = px(x, y)
    view.send_mouse_move_event(p, 0)
    view.send_mouse_press_event(p, b)
    view.send_mouse_release_event(p, b)


def placed():
    out = []
    for i in cell.each_inst():
        p = i.pcell_parameters_by_name()
        c = i.dbbox().center()
        out.append((p["layers"], p["rows"], p["cols"], round(c.x, 3), round(c.y, 3)))
    return sorted(out)


# O: the dialog (answered here), then every click places a via centred on the mouse, until Esc
real_ask = vias.ask_via
vias.ask_via = lambda parent, current: {"layers": "m1-m2", "rows": 1, "cols": 2}
try:
    view.send_mouse_move_event(px(0.0, 0.0), 0)
    mw.menu().action("openlayout_menu.via").trigger()
finally:
    vias.ask_via = real_ask
click(0.0, 0.0)
click(0.2, 0.1)
want = [("m1-m2", 1, 2, 0.0, 0.0), ("m1-m2", 1, 2, 0.2, 0.1)]
check("each click places the chosen via, centred on the mouse (to a grid step)",
      len(placed()) == 2 and all(a[:3] == b[:3] and abs(a[3] - b[3]) <= 0.0015 and abs(a[4] - b[4]) <= 0.0015
                                 for a, b in zip(placed(), want)), placed())
mw.menu().action("edit_menu.cancel").trigger()      # Esc
click(0.3, -0.1)
check("Esc ends placing", len(placed()) == 2, placed())
mw.cm_undo()
check("a placed via is one undo step", len(placed()) == 1, placed())

vias.ask_via = lambda parent, current: {"layers": "lisd-m3", "rows": 1, "cols": 1}
try:
    view.send_mouse_move_event(px(-0.1, 0.0), 0)
    mw.menu().action("openlayout_menu.via").trigger()
finally:
    vias.ask_via = real_ask
click(-0.1, 0.0)
click(0.3, 0.2, R)
click(0.3, 0.25)
check("right click ends placing; stacks place too", [p[0] for p in placed()] == ["lisd-m3", "m1-m2"], placed())

print("PASS vias" if not failures else f"FAIL vias: {', '.join(failures)}")
