"""The Generate Layout form, like Virtuoso's Generate All From Source (I/O Pins tab).

One row per schematic pin - the ports, then the supplies the cell uses: Create (check box), name,
direction, metal layer and the pin size (the layer's minimum width, a square). Pins the layout has
already are listed unchecked ("exists"); with the standard-cell frame the VDD / VSS rails are the
supply pins, so those start unchecked too. Above the table, the checked pins can all be set to one
layer. Below it, the standard-cell frame / boundary at the origin (when the cell has none).

ask_generate() returns {"pins": {name: metal}, "frame": bool} or None (cancelled).
"""
import json
import os
from pathlib import Path

import pya

from .asap7 import METALS, MIN_WIDTH

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))

DIRS = {"I": "input", "O": "output", "B": "inout"}
COL_CREATE, COL_NAME, COL_DIR, COL_LAYER, COL_SIZE = range(5)


def _size(metal: str) -> str:
    w = MIN_WIDTH[metal]
    return f"{w} x {w} nm"


def ask_generate(parent, cell_name: str, table: dict):
    """The form; table as from generate.pin_table()."""
    dlg = pya.QDialog(parent)
    dlg.windowTitle = f"Generate Layout - {cell_name}"
    # check boxes with an outline: with the dark theme an unchecked box would be invisible
    ui = json.loads((FLOW / "share/theme/openlayout.json").read_text())["ui"]
    check = (FLOW / "share/icons/check.svg").as_posix()
    dlg.styleSheet = (
        f"QCheckBox::indicator, QTableView::indicator {{ width: 13px; height: 13px; border: 1px solid {ui['dim']};"
        f" border-radius: 2px; background: {ui['base']}; }}"
        f"QCheckBox::indicator:checked, QTableView::indicator:checked {{ background: {ui['accent']};"
        f" border-color: {ui['accent']}; image: url({check}); }}")
    lay = pya.QVBoxLayout(dlg)
    lay.addWidget(pya.QLabel("I/O pins to create (a pin is a square of the layer's minimum width on its pin purpose):", dlg))

    top = pya.QHBoxLayout()
    top.addWidget(pya.QLabel("Layer for the checked pins:", dlg))
    all_layer = pya.QComboBox(dlg)
    for m in METALS:
        all_layer.addItem(m.upper())
    top.addWidget(all_layer)
    apply_all = pya.QPushButton("Apply", dlg)
    top.addWidget(apply_all)
    top.addStretch(1)
    lay.addLayout(top)

    pins = table["pins"]
    grid = pya.QTableWidget(dlg)
    grid.setColumnCount(5)
    grid.setRowCount(len(pins))
    grid.setHorizontalHeaderLabels(["Create", "Pin", "Direction", "Layer", "Size"])
    rails = table["frame"] or table["has_mos"]
    combos = []
    for r, pin in enumerate(pins):
        check = pya.QTableWidgetItem("exists" if pin["exists"] else "")
        check.flags = pya.Qt.ItemIsUserCheckable | pya.Qt.ItemIsEnabled
        on = not pin["exists"] and not (pin["supply"] and rails)
        check.checkState = pya.Qt.Checked if on else pya.Qt.Unchecked
        grid.setItem(r, COL_CREATE, check)
        for c, text in ((COL_NAME, pin["name"]), (COL_DIR, DIRS.get(pin["dir"], pin["dir"])),
                        (COL_SIZE, _size("m1"))):
            item = pya.QTableWidgetItem(text)
            item.flags = pya.Qt.ItemIsEnabled
            grid.setItem(r, c, item)
        combo = pya.QComboBox(grid)
        for m in METALS:
            combo.addItem(m.upper())
        combo.currentIndexChanged = (lambda row: lambda i: grid.item(row, COL_SIZE).setText(_size(METALS[i])))(r)
        grid.setCellWidget(r, COL_LAYER, combo)
        combos.append(combo)
    grid.resizeColumnsToContents()
    grid.setMinimumWidth(460)
    grid.setMinimumHeight(min(80 + 30 * len(pins), 420))
    lay.addWidget(grid)

    def apply_layer():
        for r, combo in enumerate(combos):
            if grid.item(r, COL_CREATE).checkState == pya.Qt.Checked:
                combo.currentIndex = all_layer.currentIndex
    apply_all.clicked = apply_layer

    frame_box = None
    if not table["frame"]:
        text = ("Create the standard-cell frame (boundary at 0, 0, VDD / VSS rails)" if table["has_mos"]
                else "Create the cell boundary at (0, 0)")
        frame_box = pya.QCheckBox(text, dlg)
        frame_box.checked = True
        frame_box.toggled = lambda on: [grid.item(r, COL_CREATE).setCheckState(
            pya.Qt.Unchecked if (on and table["has_mos"]) or pin["exists"] else pya.Qt.Checked)
            for r, pin in enumerate(pins) if pin["supply"]]
        lay.addWidget(frame_box)

    buttons = pya.QDialogButtonBox(dlg)
    ok = buttons.addButton("Generate", pya.QDialogButtonBox.AcceptRole)
    buttons.addButton(pya.QDialogButtonBox.Cancel)
    buttons.accepted = lambda: dlg.accept()
    buttons.rejected = lambda: dlg.reject()
    ok.setDefault(True)
    lay.addWidget(buttons)

    if dlg.exec_() != 1:                     # 1 = QDialog::Accepted
        return None
    chosen = {}
    for r, pin in enumerate(pins):
        if grid.item(r, COL_CREATE).checkState == pya.Qt.Checked:
            chosen[pin["name"]] = METALS[combos[r].currentIndex]
    return {"pins": chosen, "frame": frame_box.checked if frame_box is not None else True}
