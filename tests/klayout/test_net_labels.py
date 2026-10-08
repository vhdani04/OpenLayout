# Net names on the layout's shapes: which net each shape carries (from the schematic link, else
# the pin labels), and the labels drawn in a view - readable sizes only, rotated along vertical
# shapes, hidden layers unlabelled, shorts named twice. KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_net_labels.py
import os
import shutil
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path[:0] = [str(HOME / "klayout" / "python"), str(HOME / "python")]

import pya  # noqa: E402

from openlayout.workarea import Workarea  # noqa: E402
from openlayout_kl import connectivity, generate, net_labels  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def read(path):
    ly = pya.Layout()
    ly.technology_name = "asap7"
    ly.read(str(path))
    return ly


wa = Workarea.create(Path(tempfile.mkdtemp()) / "wa", "testlib")
lib = wa.library("testlib")
(lib.path / "inv").mkdir()
shutil.copy(HOME / "tests/klayout/inv_pins.sch", lib.path / "inv" / "inv.sch")
generate.generate(lib.path / "inv" / "inv.sch")
gds = lib.path / "inv" / "inv.gds"
conn = connectivity.load_conn(gds)

# 1. names from the schematic link: every net, on the layers it is drawn on
ly = read(gds)
top = ly.cell("inv")
shapes = connectivity.net_shapes(ly, top, conn)
by_layer = {}
for name, short, layer, polys in shapes:
    by_layer.setdefault(name, set()).add(layer)
check("linked: every schematic net is named", {"A", "Y", "VDD", "VSS"} <= set(by_layer), sorted(by_layer))
check("linked: the gates carry the input net", "gate" in by_layer.get("A", set()), by_layer.get("A"))
check("linked: source/drain contacts carry their nets", "lisd" in by_layer.get("Y", set()), by_layer.get("Y"))
check("linked: no shorts", not any(s for _, s, _, _ in shapes))

# 2. without a link: only the nets with a pin label are named
plain = read(gds)
pnames = {n for n, _, _, _ in connectivity.net_shapes(plain, plain.cell("inv"), None)}
check("unlinked: names from the pin labels", {"A", "Y"} <= pnames and "gate" not in pnames, sorted(pnames))

# 3. a short: the joined metal carries both names
short_ly = read(gds)
st = short_ly.cell("inv")
pins = {t.term: t.point for t in connectivity.terminals(short_ly, st, conn)[0] if t.owner is None}
a, y = pins["A"], pins["Y"]
st.shapes(short_ly.layer(19, 0)).insert(pya.DBox(min(a.x, y.x) - 0.01, min(a.y, y.y) - 0.01,
                                                 max(a.x, y.x) + 0.01, max(a.y, y.y) + 0.01))
shorted = [(n, s) for n, s, _, _ in connectivity.net_shapes(short_ly, st, conn) if s]
check("short: both names, marked", any(n == "A | Y" for n, _ in shorted), shorted[:3])

# 4. in a view: readable labels only, rotated along vertical shapes, hidden layers skipped
mw = pya.MainWindow.instance()
mw.resize(1400, 1000)
mw.load_layout(str(gds), "asap7", 0)
view = mw.current_view()
labels = net_labels.NetLabels(mw)
net_labels.set_enabled(True)
# the headless view is 100 x 100 pixels: zoom to 0.12 um around an input gate, as a user would
gate = next(t.point for t in connectivity.terminals(ly, top, conn)[0] if t.term == "g")
focus = pya.DBox(gate.x - 0.06, gate.y - 0.06, gate.x + 0.06, gate.y + 0.06)
view.zoom_box(focus)
labels.refresh(force=True)
fit = labels.labels(view)
check("view: labels drawn when zoomed in", len(fit) > 0 and len(labels.markers) > 0, f"{len(fit)} labels, {len(labels.markers)} markers")
check("view: vertical shapes get rotated labels", any(abs(tr.angle - 90) < 1e-6 for _, _, tr in fit))
texts = {t for t, _, _ in fit}
check("view: the input net is labelled", "A" in texts, sorted(texts))
bb = top.dbbox()
view.zoom_box(pya.DBox(bb.center().x - 200, bb.center().y - 200, bb.center().x + 200, bb.center().y + 200))
check("view: nothing drawn when too small to read", len(labels.labels(view)) == 0)
view.zoom_box(focus)
it = view.begin_layers()
while not it.at_end():                         # hide the gate layer
    lp = it.current()
    if lp.source_layer == 7 and lp.source_datatype == 0:
        new = lp.dup()
        new.visible = False
        view.set_layer_properties(it, new)
    it.next()
check("view: hidden layers stay unlabelled", len(labels.labels(view)) < len(fit),
      f"{len(labels.labels(view))} < {len(fit)}")
net_labels.set_enabled(False)
check("view: switched off - no markers", len(labels.markers) == 0)
net_labels.set_enabled(True)
check("view: switched back on", len(labels.markers) > 0)

print("PASS net_labels" if not failures else f"FAIL net_labels: {', '.join(failures)}")
