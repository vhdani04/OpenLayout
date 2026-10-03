# LSW + preferences, run in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_lsw.py
import os
import re
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl import gui  # noqa: E402
from openlayout_kl.lsw import USED  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
ui = gui.start(mw)
check("OpenLayout UI loaded", ui is not None and ui.lsw is not None and ui.nets is not None)

gds = Path(tempfile.mkdtemp()) / "l.gds"
ly = pya.Layout()
ly.dbu = 0.00025
top = ly.create_cell("TOP")
top.shapes(ly.layer(19, 0)).insert(pya.DBox(0, 0, 0.1, 0.018))   # M1
top.shapes(ly.layer(20, 0)).insert(pya.DBox(0, 0.05, 0.1, 0.068))  # M2
ly.write(str(gds))
mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
lsw = ui.lsw
lsw.refresh()

leaves = [it for h, it in lsw.entries() if it is not None]
m1 = next(it for it in leaves if it.current().name == "M1 drawing")
view.current_layer = m1
lsw.none_visible()
visible = [it.current().name for it in lsw._all_leaves() if it.current().visible]
check("NV keeps only the current layer visible", visible == ["M1 drawing"], visible)
lsw.all_visible()
check("AV shows all layers", all(it.current().visible for it in lsw._all_leaves()))

lsw.tabs.setCurrentIndex(USED)
lsw.refresh()
shown = [lsw.items[r].text for r, it in enumerate(lsw.rows) if it is not None]
check("Used tab lists only layers with shapes", shown == ["M1 drawing", "M2 drawing"], shown)
view.active_cellview().cell.shapes(view.active_cellview().layout().layer(21, 0)).insert(
    pya.DBox(0.01, 0.0, 0.028, 0.018))  # add V1
lsw.poll()
shown = [lsw.items[r].text for r, it in enumerate(lsw.rows) if it is not None]
check("Used tab follows edits", "V1 drawing" in shown, shown)

headers = [lsw.items[r].text for r, it in enumerate(lsw.rows) if it is None]
lsw.tabs.setCurrentIndex(0)
lsw.refresh()
all_headers = [lsw.items[r].text for r, it in enumerate(lsw.rows) if it is None]
check("All tab shows pin/label groups", "Pins" in all_headers and "Labels" in all_headers, all_headers)

check("dotted grid", mw.get_config("grid-style1") == "dots" and mw.get_config("grid-style2") == "dots")
check("Manhattan editing", mw.get_config("edit-connect-angle-mode") == "ortho"
      and mw.get_config("edit-move-angle-mode") == "ortho")
templates = mw.get_config("ruler-templates-v2")
ruler = re.search(r"title=Ruler,[^;]*angle_constraint=(\w+)", templates)
check("rulers constrained to the axes", ruler is not None and ruler.group(1) == "ortho",
      ruler.group(1) if ruler else templates[:80])
check("one layer panel (KLayout's hidden)", mw.get_config("show-layer-panel") == "false"
      and mw.get_config("show-layer-toolbox") == "false")
check("P is the OpenLayout path tool", mw.get_key_bindings().get("edit_menu.mode_menu.openlayout_path") == "P")
check("built-in path tool hidden", not mw.menu().action("@toolbar.path").visible)

print("PASS lsw" if not failures else f"FAIL lsw: {', '.join(failures)}")
