"""The Generate Layout form (the instances to place and the I/O pins to create).

Two tabs:
  Instances: one row per kind of instance (a sub-cell, or a transistor model with its fins and
    fingers) with its count, e.g. b2SRAMsbc x32. Ticking a row ticks all of its instances;
    double-clicking it opens a window listing them one by one. A row with only some ticked shows
    a partial tick. Every instance starts ticked (those in the layout already are updated).
  Pins: one row per schematic pin - the ports, then the supplies the cell uses: Create (check box),
    name, direction, metal layer and the pin size (the layer's minimum width, a square). Pins the
    layout has already are listed unchecked ("exists"); with the standard-cell frame the VDD / VSS
    rails are the supply pins, so those start unchecked too. Above the table, the checked pins can
    all be set to one layer.
Both tabs have Select All / Deselect All. Below the tabs, the standard-cell frame / boundary at the
origin (when the cell has none).

ask_generate() returns {"pins": {name: metal}, "frame": bool, "instances": set of names, or None
when all are ticked} or None (cancelled).
"""
import json
import os
from pathlib import Path

import pya

from .asap7 import METALS, MIN_WIDTH

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))

DIRS = {"I": "input", "O": "output", "B": "inout"}
COL_CREATE, COL_NAME, COL_DIR, COL_LAYER, COL_SIZE = range(5)       # Pins tab
COL_PLACE, COL_TYPE, COL_COUNT, COL_STATUS = range(4)               # Instances tab


def _size(metal: str) -> str:
    w = MIN_WIDTH[metal]
    return f"{w} x {w} nm"


def _style():
    # check boxes with an outline: with the dark theme an unchecked box would be invisible
    ui = json.loads((FLOW / "share/theme/openlayout.json").read_text())["ui"]
    check = (FLOW / "share/icons/check.svg").as_posix()
    return (f"QCheckBox::indicator, QTableView::indicator {{ width: 13px; height: 13px; border: 1px solid {ui['dim']};"
            f" border-radius: 2px; background: {ui['base']}; }}"
            f"QCheckBox::indicator:checked, QTableView::indicator:checked {{ background: {ui['accent']};"
            f" border-color: {ui['accent']}; image: url({check}); }}"
            f"QTableView::indicator:indeterminate {{ background: {ui['dim']}; border-color: {ui['accent']}; }}")


def _all_buttons(parent, layout, set_all):
    """Select All / Deselect All, calling set_all(True / False)."""
    row = pya.QHBoxLayout()
    on = pya.QPushButton("Select All", parent)
    off = pya.QPushButton("Deselect All", parent)
    on.objectName, off.objectName = "select_all", "deselect_all"
    on.clicked = lambda: set_all(True)
    off.clicked = lambda: set_all(False)
    row.addWidget(on)
    row.addWidget(off)
    row.addStretch(1)
    layout.addLayout(row)


def _cell(text):
    item = pya.QTableWidgetItem(text)
    item.flags = pya.Qt.ItemIsEnabled
    return item


def _state(ticks):
    n = sum(ticks)
    return pya.Qt.Checked if n == len(ticks) else pya.Qt.Unchecked if n == 0 else pya.Qt.PartiallyChecked


def pick_instances(parent, kind: str, members: list, chosen: dict) -> bool:
    """The window behind a row of the Instances tab: each instance of one kind with its own tick.
    members: [{"name", "exists"}]; chosen {name: bool} is updated on OK. Returns True on OK."""
    dlg = pya.QDialog(parent)
    dlg.windowTitle = f"{kind} x{len(members)}"
    dlg.styleSheet = _style()
    lay = pya.QVBoxLayout(dlg)
    lay.addWidget(pya.QLabel(f"The {kind} instances to place or update:", dlg))
    grid = pya.QTableWidget(dlg)
    grid.objectName = "members"
    grid.setColumnCount(3)
    grid.setRowCount(len(members))
    grid.setHorizontalHeaderLabels(["Place", "Instance", "Layout"])
    for r, m in enumerate(members):
        tick = pya.QTableWidgetItem("")
        tick.flags = pya.Qt.ItemIsUserCheckable | pya.Qt.ItemIsEnabled
        tick.checkState = pya.Qt.Checked if chosen[m["name"]] else pya.Qt.Unchecked
        grid.setItem(r, 0, tick)
        grid.setItem(r, 1, _cell(m["name"]))
        grid.setItem(r, 2, _cell("exists" if m["exists"] else ""))
    grid.resizeColumnsToContents()
    grid.setMinimumWidth(320)
    grid.setMinimumHeight(min(80 + 30 * len(members), 480))
    lay.addWidget(grid)
    _all_buttons(dlg, lay, lambda on: [grid.item(r, 0).setCheckState(pya.Qt.Checked if on else pya.Qt.Unchecked)
                                       for r in range(len(members))])
    buttons = pya.QDialogButtonBox(dlg)
    buttons.addButton(pya.QDialogButtonBox.Ok)
    buttons.addButton(pya.QDialogButtonBox.Cancel)
    buttons.accepted = lambda: dlg.accept()
    buttons.rejected = lambda: dlg.reject()
    lay.addWidget(buttons)
    if dlg.exec_() != 1:
        return False
    for r, m in enumerate(members):
        chosen[m["name"]] = grid.item(r, 0).checkState == pya.Qt.Checked
    return True


def _instances_tab(dlg, tabs, table):
    """The Instances tab; returns {name: bool}, kept up to date while the form is open."""
    page = pya.QWidget(dlg)
    lay = pya.QVBoxLayout(page)
    lay.addWidget(pya.QLabel("Instances to place or update (double-click a row to pick single instances):", page))
    groups = {}                                  # kind -> [{"name", "exists"}], in schematic order
    for inst in table.get("instances", []):
        groups.setdefault(inst["type"], []).append(inst)
    kinds = list(groups)
    chosen = {i["name"]: True for i in table.get("instances", [])}

    grid = pya.QTableWidget(page)
    grid.objectName = "instances"
    grid.setColumnCount(4)
    grid.setRowCount(len(kinds))
    grid.setHorizontalHeaderLabels(["Place", "Instance", "Count", "Layout"])
    busy = [False]                               # while the code itself sets the ticks

    def show(r):
        busy[0] = True
        grid.item(r, COL_PLACE).setCheckState(_state([chosen[m["name"]] for m in groups[kinds[r]]]))
        busy[0] = False

    for r, kind in enumerate(kinds):
        tick = pya.QTableWidgetItem("")
        tick.flags = pya.Qt.ItemIsUserCheckable | pya.Qt.ItemIsEnabled
        grid.setItem(r, COL_PLACE, tick)
        grid.setItem(r, COL_TYPE, _cell(kind))
        grid.setItem(r, COL_COUNT, _cell(f"x{len(groups[kind])}"))
        n = sum(m["exists"] for m in groups[kind])
        grid.setItem(r, COL_STATUS, _cell("" if n == 0 else "all exist" if n == len(groups[kind]) else f"{n} exist"))
        show(r)

    def ticked(item):
        if busy[0] or item.column() != COL_PLACE:
            return
        on = item.checkState != pya.Qt.Unchecked
        for m in groups[kinds[item.row()]]:
            chosen[m["name"]] = on
        show(item.row())

    def opened(r, c):
        if pick_instances(dlg, kinds[r], groups[kinds[r]], chosen):
            show(r)

    grid.itemChanged = ticked
    grid.cellDoubleClicked = opened
    grid.resizeColumnsToContents()
    grid.setMinimumWidth(460)
    grid.setMinimumHeight(min(80 + 30 * len(kinds), 420))
    lay.addWidget(grid)

    def set_all(on):
        for name in chosen:
            chosen[name] = on
        for r in range(len(kinds)):
            show(r)
    _all_buttons(page, lay, set_all)
    tabs.addTab(page, f"Instances ({len(chosen)})")
    return chosen


def ask_generate(parent, cell_name: str, table: dict):
    """The form; table as from generate.pin_table()."""
    dlg = pya.QDialog(parent)
    dlg.windowTitle = f"Generate Layout - {cell_name}"
    dlg.styleSheet = _style()
    lay = pya.QVBoxLayout(dlg)
    tabs = pya.QTabWidget(dlg)
    tabs.objectName = "tabs"
    lay.addWidget(tabs)
    chosen = _instances_tab(dlg, tabs, table)

    page = pya.QWidget(dlg)
    plays = pya.QVBoxLayout(page)
    plays.addWidget(pya.QLabel("I/O pins to create (a pin is a square of the layer's minimum width on its pin purpose):", page))
    top = pya.QHBoxLayout()
    top.addWidget(pya.QLabel("Layer for the checked pins:", page))
    all_layer = pya.QComboBox(page)
    for m in METALS:
        all_layer.addItem(m.upper())
    top.addWidget(all_layer)
    apply_all = pya.QPushButton("Apply", page)
    top.addWidget(apply_all)
    top.addStretch(1)
    plays.addLayout(top)

    pins = table["pins"]
    grid = pya.QTableWidget(page)
    grid.objectName = "pins"
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
            grid.setItem(r, c, _cell(text))
        combo = pya.QComboBox(grid)
        for m in METALS:
            combo.addItem(m.upper())
        combo.currentIndexChanged = (lambda row: lambda i: grid.item(row, COL_SIZE).setText(_size(METALS[i])))(r)
        grid.setCellWidget(r, COL_LAYER, combo)
        combos.append(combo)
    grid.resizeColumnsToContents()
    grid.setMinimumWidth(460)
    grid.setMinimumHeight(min(80 + 30 * len(pins), 420))
    plays.addWidget(grid)
    _all_buttons(page, plays, lambda on: [grid.item(r, COL_CREATE).setCheckState(
        pya.Qt.Checked if on else pya.Qt.Unchecked) for r in range(len(pins))])
    tabs.addTab(page, f"Pins ({len(pins)})")

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
    picked = {}
    for r, pin in enumerate(pins):
        if grid.item(r, COL_CREATE).checkState == pya.Qt.Checked:
            picked[pin["name"]] = METALS[combos[r].currentIndex]
    instances = None if all(chosen.values()) else {n for n, on in chosen.items() if on}
    return {"pins": picked, "frame": frame_box.checked if frame_box is not None else True, "instances": instances}
