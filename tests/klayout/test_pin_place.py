# Place Pins (pin_place.py, OpenLayout > Place Pins…): whole buses of pins at once - on the nets'
# terminals, on wire ends, along a side of the cell (aligned or spaced, on the SADP tracks of M4 - M7).
# Run in KLayout with a main window (headless):
#   klayout -e -z -nc -r tests/klayout/test_pin_place.py
import json
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path[:0] = [str(HOME / "klayout" / "python"), str(HOME / "python")]

import pya  # noqa: E402

from openlayout_kl import gui, pin_place, pin_place_form  # noqa: E402
from openlayout_kl.asap7 import LAYERS, PIN  # noqa: E402
from openlayout_kl.connectivity import PREFIX, PROP  # noqa: E402
from openlayout_kl.pcells import LIBRARY, register_library  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


mw = pya.Application.instance().main_window()
gui.start(mw)
register_library()

# A 2 x 4 array of a bit cell like b2SRAMsbc: BL a vertical M3 wire (its pin shape the whole wire),
# WL a horizontal M2 wire across the cell with a small pin shape in the middle. Columns drive
# BL[3] ... BL[0], rows WL[0] (bottom) and WL[1]; EN is a port no instance connects to.
W, H = 0.756, 0.27
PORTS = ["BL[3]", "BL[2]", "BL[1]", "BL[0]", "WL[1]", "WL[0]", "EN"]


def make(path):
    ly = pya.Layout()
    ly.dbu = 0.00025
    ly.technology_name = "asap7"
    bit = ly.create_cell("BIT")
    bit.shapes(ly.layer(LAYERS["boundary"], 0)).insert(pya.DBox(0, 0, W, H))
    for li in (ly.layer(LAYERS["m3"], 0), ly.layer(LAYERS["m3"], PIN)):
        bit.shapes(li).insert(pya.DBox(0.477, 0, 0.495, H))
    bit.shapes(ly.layer(LAYERS["m3"], PIN)).insert(pya.DText("BL", pya.DTrans(0.486, 0.135)))
    bit.shapes(ly.layer(LAYERS["m2"], 0)).insert(pya.DBox(0, 0.144, W, 0.162))
    bit.shapes(ly.layer(LAYERS["m2"], PIN)).insert(pya.DBox(0.36, 0.144, 0.396, 0.162))
    bit.shapes(ly.layer(LAYERS["m2"], PIN)).insert(pya.DText("WL", pya.DTrans(0.378, 0.153)))
    top = ly.create_cell("ARR")
    insts = {}
    for r in range(2):
        for c in range(4):
            i = top.insert(pya.DCellInstArray(bit.cell_index(), pya.DTrans(c * W, r * H)))
            name = f"I{r}{c}"
            i.set_property(PROP, PREFIX + name)
            insts[name] = {"kind": "cell", "lib": "", "cell": "BIT",
                           "terminals": {"BL": f"BL[{3 - c}]", "WL": f"WL[{r}]"}}
    # the WL[0] wire routed out past the right side on M2; a via PCell (must stay a PCell)
    top.shapes(ly.layer(LAYERS["m2"], 0)).insert(pya.DBox(2.9, 0.144, 3.1, 0.162))
    via = ly.create_cell("via", LIBRARY, {})
    if via is not None:
        top.insert(pya.DCellInstArray(via.cell_index(), pya.DTrans(1.0, 1.0)))
    ly.write(str(path))
    conn = {"version": 1, "ports": PORTS, "pins": {p: "B" for p in PORTS}, "instances": insts}
    path.with_name(path.stem + ".ol.json").write_text(json.dumps(conn))
    return conn


tmp = Path(tempfile.mkdtemp())
gds = tmp / "ARR.gds"
conn = make(gds)


def load():
    ly = pya.Layout()
    ly.technology_name = "asap7"
    ly.read(str(gds))
    return ly, ly.cell("ARR")


def pins(top):
    """{name: (metal, x, y)} of the top cell's pin labels (rounded), and the pin-shape count"""
    out, n = {}, 0
    ly = top.layout()
    for metal in ("m1", "m2", "m3", "m4", "m5"):
        li = ly.find_layer(LAYERS[metal], PIN)
        if li is None:
            continue
        for s in top.shapes(li).each():
            if s.is_text():
                out[s.text_string] = (metal, round(s.dtext.x, 4), round(s.dtext.y, 4))
            else:
                n += 1
    return out, n


# 1. names: a bus by its base name, a range, a bit, unknown names
check("a bus by its base name is its bits in port order",
      pin_place.resolve(["BL"], PORTS) == (["BL[3]", "BL[2]", "BL[1]", "BL[0]"], []))
check("ranges, bits and plain pins; no repeats; unknown names reported",
      pin_place.resolve(["BL[0:1]", "BL[1]", "EN", "Q[1:0]"], PORTS) == (["BL[0]", "BL[1]", "EN"], ["Q[1]", "Q[0]"]),
      pin_place.resolve(["BL[0:1]", "BL[1]", "EN", "Q[1:0]"], PORTS))
check("bus groups for the window", [g for g, _ in pin_place.bus_groups(PORTS)] == ["BL", "WL", "EN"])

# 2. on the terminals: each pin on its net's terminal nearest the side
ly, top = load()
rep = pin_place.place_pins(top, conn, ["BL", "WL", "EN"], mode="terminals", edge="top")
got, n = pins(top)
check("BL pins on the top end of the top row's bit lines (M3, flush with the end)",
      [got[f"BL[{3 - c}]"] for c in range(4)] == [("m3", round(c * W + 0.486, 4), 0.531) for c in range(4)],
      [got.get(f"BL[{3 - c}]") for c in range(4)])
check("WL pins on their own row's WL pin shape (M2)", got["WL[1]"][0] == "m2" and abs(got["WL[1]"][2] - 0.423) < 1e-6
      and abs(got["WL[0]"][2] - 0.153) < 1e-6, (got["WL[1]"], got["WL[0]"]))
check("a port without terminals is reported, not placed", "EN" not in got
      and rep["problems"] == ["EN: no terminal of the net"], rep["problems"])
check("terminal pins sit on drawn metal (no OL.PIN) and keep apart", rep["off_metal"] == [] and rep["warnings"] == [],
      (rep["off_metal"], rep["warnings"]))
check("one pin shape per pin", n == 6, n)

# 3. again, another side: the pins move (no copies); without replace they stay
rep = pin_place.place_pins(top, conn, ["BL"], mode="terminals", edge="bottom")
got, n = pins(top)
check("placing again moves the pins", rep["moved"] == ["BL[3]", "BL[2]", "BL[1]", "BL[0]"]
      and got["BL[3]"] == ("m3", 0.486, 0.009) and n == 6, (rep["moved"], got["BL[3]"], n))
rep = pin_place.place_pins(top, conn, ["BL"], mode="terminals", edge="top", replace=False)
check("replace=False leaves existing pins alone", rep["skipped"] == ["BL[3]", "BL[2]", "BL[1]", "BL[0]"]
      and pins(top)[0]["BL[3]"] == ("m3", 0.486, 0.009), rep["skipped"])
rep = pin_place.place_pins(top, conn, ["BL[2]"], mode="terminals", metal="m2")
check("a metal the net has no terminal on is reported", rep["problems"] == ["BL[2]: no terminal of the net on M2"],
      rep["problems"])

# 4. along a side, aligned with the terminals, on M5: x onto the M5 tracks (48 nm, centres 48 k + 12)
ly, top = load()
rep = pin_place.place_pins(top, conn, ["BL"], mode="edge", edge="top", metal="m5")
got, _ = pins(top)
check("M5 pins above the bit lines, snapped onto the tracks, flush inside the top",
      got["BL[3]"] == ("m5", 0.492, 0.528) and got["BL[0]"] == ("m5", round(round((3 * W + 0.486 - 0.012) / 0.048)
                                                                                 * 0.048 + 0.012, 4), 0.528),
      (got["BL[3]"], got["BL[0]"]))
check("edge pins away from wires are reported for OL.PIN", sorted(rep["off_metal"]) == sorted(pin_place.resolve(["BL"], PORTS)[0]),
      rep["off_metal"])
rep = pin_place.place_pins(top, conn, ["BL"], mode="edge", edge="top")
check("aligned on the terminal's own metal (M3): right on the bit lines, connected",
      pins(top)[0]["BL[3]"] == ("m3", 0.486, 0.531) and rep["off_metal"] == [], (pins(top)[0]["BL[3]"], rep["off_metal"]))

# 5. evenly spaced: M4 on the left side - y onto the M4 tracks, in port order or reversed
ly, top = load()
pin_place.place_pins(top, conn, ["WL"], mode="edge", edge="left", metal="m4", align=False, pitch=96, start=48)
got, _ = pins(top)
check("spaced M4 pins: on tracks, one pitch apart, port order bottom up",
      got["WL[1]"] == ("m4", 0.012, 0.06) and got["WL[0]"] == ("m4", 0.012, 0.156), (got["WL[1]"], got["WL[0]"]))
pin_place.place_pins(top, conn, ["WL"], mode="edge", edge="left", metal="m4", align=False, pitch=96, start=48,
                     reverse=True)
got, _ = pins(top)
check("reversed: the last bit first", got["WL[0]"][2] == 0.06 and got["WL[1]"][2] == 0.156, got)
pin_place.place_pins(top, conn, ["EN"], mode="edge", edge="top", metal="m4", align=False)
check("a horizontal SADP metal on the top side: the highest track inside the cell",
      pins(top)[0]["EN"] == ("m4", 0.048, 0.492), pins(top)[0]["EN"])
rep = pin_place.place_pins(top, conn, ["BL", "WL"], mode="edge", edge="left", metal="m4", align=False, pitch=144)
check("spaced pins that do not fit on the side are reported, not placed past its end",
      [p.split(":")[0] for p in rep["problems"]] == ["WL[1]", "WL[0]"] and len(rep["placed"]) == 4
      and all(p.y < 0.54 for _, _, p in rep["placed"]), (rep["problems"], rep["placed"]))
rep = pin_place.place_pins(top, conn, ["BL"], mode="edge", edge="bottom", metal="m3", align=False, pitch=10)
check("pins closer than the metal allows are reported (every pair within 36 nm)", len(rep["warnings"]) == 6
      and "BL[3] and BL[2] pins on M3 are 10 nm apart" in rep["warnings"], rep["warnings"])
try:
    pin_place.place_pins(top, conn, ["BL"], mode="edge", edge="auto")
    check("along a side needs the side", False)
except ValueError:
    check("along a side needs the side", True)

# 6. on the wires: the end of the net's routing nearest the side
ly, top = load()
rep = pin_place.place_pins(top, conn, ["WL"], mode="wires", edge="right", metal="m2")
got, _ = pins(top)
check("WL[0]'s pin on the end of its wire past the right side", got["WL[0]"] == ("m2", 3.091, 0.153), got.get("WL[0]"))
check("WL[1] (sub-cell wiring only) on its last cell's right end", got["WL[1]"] == ("m2", 3.015, 0.423), got.get("WL[1]"))
rep = pin_place.place_pins(top, conn, ["BL[3]"], mode="wires", edge="auto")
check("auto: the net's top metal, nearest any side", pins(top)[0]["BL[3]"][0] == "m3" and rep["problems"] == [],
      (pins(top)[0]["BL[3]"], rep["problems"]))
rep = pin_place.place_pins(top, conn, ["BL[3]"], mode="wires", metal="m4")
check("no wiring on that metal: reported", rep["problems"] == ["BL[3]: no M4 wiring of the net found"], rep["problems"])

# 7. batch on a file: written back, PCells stay PCells
out = tmp / "ARR_pins.gds"
rep = pin_place.place_pins_file(gds, ["BL", "WL"], out=out, mode="terminals", edge="top")
ly2 = pya.Layout()
ly2.technology_name = "asap7"
ly2.read(str(out))
got, _ = pins(ly2.cell("ARR"))
check("batch: the file gets the pins", len(got) == 6 and len(rep["placed"]) == 6, got)
pc = [i for i in ly2.cell("ARR").each_inst() if i.cell.name.startswith("via")]
check("batch: the via is still a PCell", pc and pc[0].is_pcell() and pc[0].pcell_declaration().name() == "via",
      [i.cell.name for i in pc])

# 8. the window: defaults, and the menu command (one undo step)
rows = pin_place_form.bus_rows(top, conn)
check("window rows: buses with bits, pins already there, terminal metals",
      [(r["name"], len(r["bits"]), r["have"], r["metals"]) for r in rows]
      == [("BL", 4, 1, "M3"), ("WL", 2, 2, "M2"), ("EN", 1, 0, "-")], rows)


def run_form(edit=None, cell=None):
    timer = pya.QTimer(mw)
    timer.interval = 300
    timer.singleShot = True

    def act():
        d = pya.QApplication.activeModalWidget()
        if d is None:
            return
        try:
            if edit:
                edit(d)
        finally:
            d.accept()
    timer.timeout = act
    timer.start()
    return pin_place_form.ask_place_pins(mw, cell or top, conn, gui.UI)


answer = run_form()
check("window defaults: unfinished buses, on the terminals, nearest side, their own metal",
      answer == {"mode": "terminals", "edge": "auto", "metal": "auto", "align": True, "pitch": None, "start": None,
                 "reverse": False, "replace": True, "names": ["BL", "EN"]}, answer)


def widgets(d, kind):
    """the dialog's widgets of a kind, in creation order"""
    out = []
    for c in d.children():
        if type(c).__name__.startswith(kind):
            out.append(c)
        out += widgets(c, kind)
    return out


def edit(d):
    combos = widgets(d, "QComboBox")
    mode, edge, metal = combos[0], combos[1], combos[2]
    mode.currentIndex = pin_place.MODES.index("edge")
    edge.currentIndex = 3                      # left
    align = [c for c in widgets(d, "QCheckBox") if c.text.startswith("Aligned")][0]
    align.checked = False
    metal.currentIndex = 1 + 3                 # M4


answer = run_form(edit)
check("window: along the left side, spaced on M4 at its track pitch",
      answer["mode"] == "edge" and answer["edge"] == "left" and answer["metal"] == "m4" and not answer["align"]
      and answer["pitch"] == 48 and answer["start"] == 48, answer)

mw.load_layout(str(gds), "asap7", 1)
view = mw.current_view()
for _ in range(10):
    pya.Application.instance().process_events()
real = pin_place_form.ask_place_pins
pin_place_form.ask_place_pins = lambda parent, cell, c, ui: {"names": ["BL", "WL"], "mode": "terminals",
                                                                 "edge": "top", "metal": "auto"}
try:
    gui.instance.place_pins_dialog()
finally:
    pin_place_form.ask_place_pins = real
cell = view.active_cellview().cell
check("Place Pins… places the pins in the open layout", len(pins(cell)[0]) == 6, pins(cell)[0])
mw.cm_undo()
check("one undo takes them all away", pins(cell) == ({}, 0), pins(cell))

print("PASS pin_place" if not failures else f"FAIL pin_place: {', '.join(failures)}")
