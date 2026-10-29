"""The Place Pins window (OpenLayout > Place Pins…): which buses, where, on which metal.

One row per bus of the schematic link (a plain pin is a bus of one): Place (check box), name, bits,
how many of them the layout has already, and the metals of the net's terminals. Buses with a bit
still missing start checked. Below: where the pins go (pin_place.MODES), the side of the cell, the
metal, and for pins along a side either aligned with the nets' terminals or evenly spaced.

ask_place_pins() returns place_pins' options {"names", "mode", "edge", "metal", "align", "pitch",
"start", "reverse", "replace"} or None (cancelled). The choices are remembered for the next time.
"""
import os
from pathlib import Path

import pya

from . import pin_place
from .asap7 import METALS

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))
COL_PLACE, COL_NAME, COL_BITS, COL_HAVE, COL_METAL = range(5)
MODE_TEXT = {
    "terminals": "On the net's terminals (the sub-cells' pins)",
    "wires": "On the ends of the net's wires",
    "edge": "Along a side of the cell",
}
HINT = {
    "terminals": "Each pin goes on its net's terminal nearest the chosen side - drawn metal of the net, so "
                 "it connects (LVS) and needs no wire (DRC OL.PIN).",
    "wires": "Route the bus first: each pin goes on the end of its net's wiring on the metal, nearest "
             "the chosen side.",
    "edge": "Pins flush inside the cell's boundary. On M4 - M7 they snap onto the metal's SADP routing "
            "tracks; until the wires reach them, DRC reports them (OL.PIN).",
}
EDGE_TEXT = [("auto", "Nearest side"), ("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right")]
last = {"mode": "terminals", "edge": "auto", "metal": "auto", "align": True, "pitch": None, "start": None,
        "reverse": False, "replace": True}


def bus_rows(top, conn):
    """[{"name", "bits", "have", "metals"}] for the window, from the link's ports and the layout."""
    have = pin_place.existing_pins(top)
    terms = pin_place.terminal_shapes(top.layout(), top, conn)
    rows = []
    for name, bits in pin_place.bus_groups(conn.get("ports", [])):
        metals = sorted({m for b in bits for m, _ in terms.get(b, [])}, key=METALS.index)
        rows.append({"name": name, "bits": bits, "have": sum(1 for b in bits if b in have),
                     "metals": ", ".join(m.upper() for m in metals) or "-"})
    return rows


def _label(bits):
    return f"{bits[0]} … {bits[-1]}" if len(bits) > 2 else ", ".join(bits)


def ask_place_pins(parent, top, conn, ui):
    rows = bus_rows(top, conn)
    dlg = pya.QDialog(parent)
    dlg.windowTitle = f"Place Pins - {top.name}"
    check = (FLOW / "share/icons/check.svg").as_posix()
    dlg.styleSheet = (
        f"QCheckBox::indicator, QTableView::indicator {{ width: 13px; height: 13px; border: 1px solid {ui['dim']};"
        f" border-radius: 2px; background: {ui['base']}; }}"
        f"QCheckBox::indicator:checked, QTableView::indicator:checked {{ background: {ui['accent']};"
        f" border-color: {ui['accent']}; image: url({check}); }}")
    lay = pya.QVBoxLayout(dlg)
    lay.addWidget(pya.QLabel("Buses and pins of the schematic (a pin is a square of the metal's minimum width "
                             "with its label):", dlg))

    grid = pya.QTableWidget(dlg)
    grid.setColumnCount(5)
    grid.setRowCount(len(rows))
    grid.setHorizontalHeaderLabels(["Place", "Pin / bus", "Bits", "In the layout", "Terminals on"])
    for r, row in enumerate(rows):
        item = pya.QTableWidgetItem("")
        item.flags = pya.Qt.ItemIsUserCheckable | pya.Qt.ItemIsEnabled
        item.checkState = pya.Qt.Checked if row["have"] < len(row["bits"]) else pya.Qt.Unchecked
        grid.setItem(r, COL_PLACE, item)
        for c, text in ((COL_NAME, row["name"]), (COL_BITS, _label(row["bits"])),
                        (COL_HAVE, f"{row['have']} / {len(row['bits'])}"), (COL_METAL, row["metals"])):
            it = pya.QTableWidgetItem(text)
            it.flags = pya.Qt.ItemIsEnabled
            grid.setItem(r, c, it)
    grid.resizeColumnsToContents()
    grid.setMinimumWidth(520)
    grid.setMinimumHeight(min(80 + 30 * len(rows), 380))
    lay.addWidget(grid)
    sel = pya.QHBoxLayout()
    all_btn, none_btn = pya.QPushButton("All", dlg), pya.QPushButton("None", dlg)
    all_btn.clicked = lambda: [grid.item(r, COL_PLACE).setCheckState(pya.Qt.Checked) for r in range(len(rows))]
    none_btn.clicked = lambda: [grid.item(r, COL_PLACE).setCheckState(pya.Qt.Unchecked) for r in range(len(rows))]
    sel.addWidget(all_btn)
    sel.addWidget(none_btn)
    sel.addStretch(1)
    lay.addLayout(sel)

    form = pya.QFormLayout()
    mode = pya.QComboBox(dlg)
    for m in pin_place.MODES:
        mode.addItem(MODE_TEXT[m])
    mode.currentIndex = pin_place.MODES.index(last["mode"])
    form.addRow("Where:", mode)
    edge = pya.QComboBox(dlg)
    for _, text in EDGE_TEXT:
        edge.addItem(text)
    edge.currentIndex = [e for e, _ in EDGE_TEXT].index(last["edge"])
    form.addRow("Side of the cell:", edge)
    metal = pya.QComboBox(dlg)
    metal.addItem("The terminal's own")
    for m in METALS:
        metal.addItem(m.upper())
    metal.currentIndex = 0 if last["metal"] == "auto" else 1 + METALS.index(last["metal"])
    form.addRow("Metal:", metal)
    align = pya.QCheckBox("Aligned with the net's terminals (else evenly spaced)", dlg)
    align.checked = last["align"]
    form.addRow("Along the side:", align)
    pitch = pya.QSpinBox(dlg)
    pitch.setRange(1, 100000)
    pitch.suffix = " nm"
    form.addRow("Pitch:", pitch)
    start = pya.QSpinBox(dlg)
    start.setRange(0, 1000000)
    start.suffix = " nm"
    form.addRow("First pin (from the left / bottom side):", start)
    reverse = pya.QCheckBox("Last bit first (LSB at the left / bottom)", dlg)
    reverse.checked = last["reverse"]
    form.addRow("", reverse)
    replace = pya.QCheckBox("Move the pins the layout has already", dlg)
    replace.checked = last["replace"]
    form.addRow("", replace)
    lay.addLayout(form)
    hint = pya.QLabel("", dlg)
    hint.wordWrap = True
    hint.styleSheet = f"color: {ui['dim']};"
    lay.addWidget(hint)

    def chosen_metal():
        return "auto" if metal.currentIndex == 0 else METALS[metal.currentIndex - 1]

    def refresh(*_):
        m = pin_place.MODES[mode.currentIndex]
        on_edge = m == "edge"
        spaced = on_edge and not align.checked
        if on_edge and edge.currentIndex == 0:
            edge.currentIndex = 1                       # pins along a side need the side
        metal.setItemText(0, "The net's top metal" if m == "wires" else "The terminal's own")
        if spaced and metal.currentIndex == 0:
            metal.currentIndex = 1 + METALS.index("m3")
        align.enabled = on_edge
        for w in (pitch, start, reverse):
            w.enabled = spaced
        hint.text = HINT[m]

    def metal_pitch(*_):
        """A new metal: its track pitch for pitch and first pin."""
        m = chosen_metal()
        pitch.value = start.value = pin_place.PITCH[m if m != "auto" else "m3"]

    mode.currentIndexChanged = refresh
    align.toggled = refresh
    refresh()
    metal_pitch()
    if last["pitch"] is not None:
        pitch.value, start.value = last["pitch"], last["start"]
    metal.currentIndexChanged = metal_pitch

    buttons = pya.QDialogButtonBox(dlg)
    ok = buttons.addButton("Place", pya.QDialogButtonBox.AcceptRole)
    buttons.addButton(pya.QDialogButtonBox.Cancel)
    buttons.accepted = lambda: dlg.accept()
    buttons.rejected = lambda: dlg.reject()
    ok.setDefault(True)
    lay.addWidget(buttons)

    if dlg.exec_() != 1:                     # 1 = QDialog::Accepted
        return None
    m = pin_place.MODES[mode.currentIndex]
    spaced = m == "edge" and not align.checked
    options = {"mode": m, "edge": EDGE_TEXT[edge.currentIndex][0], "metal": chosen_metal(),
               "align": align.checked, "pitch": pitch.value if spaced else None,
               "start": start.value if spaced else None, "reverse": reverse.checked, "replace": replace.checked}
    last.update(options)
    options["names"] = [row["name"] for r, row in enumerate(rows)
                        if grid.item(r, COL_PLACE).checkState == pya.Qt.Checked]
    return options
