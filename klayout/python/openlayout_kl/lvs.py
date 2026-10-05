"""Layout versus schematic in KLayout: the ASAP7 deck (pdk/asap7/klayout/lvs/asap7.lvs) on the
cell being edited against its xschem schematic, results in KLayout's netlist browser - like
Calibre LVS from Virtuoso with the results in RVE.

run_current(): OpenLayout > Run LVS - the current cell as edited (saved or not) against the
schematic next to its layout (<cell>.sch, or the one the Layout XL link names); a standard cell
without a schematic is checked against the library CDL. show_results(): loads a batch run's
report (`openlayout lvs`, the hub's LVS button) into the layout's view.
"""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pya

from . import checks

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))
DECK = FLOW / "pdk/asap7/klayout/lvs/asap7.lvs"
RESULT_RE = re.compile(r"^RESULT LVS \S+ (\w+) circuits=(\d+) bulk=(\d+) names=(\d+)", re.M)


def schematic_for(layout_file, cell):
    """The cell's schematic: <cell>.sch next to the layout or the Layout XL link's; None if none."""
    d = Path(layout_file).parent
    sch = d / f"{cell}.sch"
    if sch.is_file():
        return sch
    link = d / f"{Path(layout_file).stem}.ol.json"
    try:
        named = json.loads(link.read_text()).get("schematic")
        if named and (d / named).is_file():
            return d / named
    except (OSError, ValueError):
        pass
    return None


def run(gds, cell, schematic=None, report=None, stdcells=None):
    """Batch LVS (as `openlayout lvs`). Returns (result dict, output text)."""
    argv = ["openlayout", "lvs", str(gds), "--cell", cell]
    if schematic:
        argv += ["--schematic", str(schematic)]
    if report:
        argv += ["--report", str(report)]
    if stdcells:
        argv += ["--stdcells", stdcells]
    res = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    out = res.stdout + res.stderr
    m = RESULT_RE.search(out)
    if not m:
        raise RuntimeError(f"LVS did not run:\n{out[-800:]}")
    return {"match": m.group(1) == "match", "circuits": int(m.group(2)), "bulk": int(m.group(3)),
            "names": int(m.group(4))}, out


def run_current(mw=None):
    """LVS of the current view's cell; the results open in the netlist browser."""
    mw = mw or pya.Application.instance().main_window()
    view = mw.current_view()
    cv = view.active_cellview() if view else None
    if cv is None or not cv.is_valid():
        pya.MessageBox.info("OpenLayout", "Open a layout first.", pya.MessageBox.Ok)
        return None
    cell = cv.cell_name
    sch = schematic_for(cv.filename(), cell) if cv.filename() else None
    if sch is None and "_ASAP7_75t_" not in cell:
        pya.MessageBox.warning("OpenLayout", f"No schematic for {cell}: LVS compares the layout with "
                               f"{cell}.sch next to the layout file.", pya.MessageBox.Ok)
        return None
    tmp = Path(tempfile.mkdtemp(prefix="ol_lvs_"))
    gds = tmp / f"{cell}.gds"
    cv.layout().write(str(gds))                 # the layout as edited
    report = tmp / f"{cell}.lvsdb"
    mw.message(f"LVS: {cell} against {sch.name if sch else 'the library CDL'} ...", 10000)
    result, out = run(gds, cell, sch, report)
    show(view, cv.index(), report)
    mw.message(f"LVS {cell}: " + describe(result), 20000)
    checks.record(cv, "lvs", result["match"], "match" if result["match"] else describe(result).split(" - ", 1)[-1])
    return result


def describe(result):
    if result["match"]:
        return "layout matches the schematic"
    parts = []
    if result["circuits"]:
        parts.append(f"{result['circuits']} circuit(s) differ")
    if result["names"]:
        parts.append(f"{result['names']} net name(s) differ")
    if result["bulk"]:
        parts.append(f"{result['bulk']} bulk connection(s) not on VDD / VSS")
    return "MISMATCH - " + ", ".join(parts or ["see the netlist browser"])


def show(view, cv_index, report):
    db = pya.LayoutVsSchematic()
    db.read(str(report))
    index = view.add_lvsdb(db)
    view.show_lvsdb(index, cv_index)
    return db


def show_results(file, cell, report, mw=None):
    """Open `report` (from a batch run) on the view showing `file` (opened if needed)."""
    mw = mw or pya.Application.instance().main_window()
    file = os.path.realpath(file)
    index = None
    for i in range(mw.views()):
        v = mw.view(i)
        for ci in range(v.cellviews()):
            if os.path.realpath(v.cellview(ci).filename()) == file:
                index = (i, ci)
    if index is None:
        mw.load_layout(file, "asap7", 1)
        index = (mw.current_view_index, 0)
    mw.select_view(index[0])
    view = mw.current_view()
    layout = view.cellview(index[1]).layout()
    if cell and layout.cell(cell) is not None:
        view.select_cell(layout.cell(cell).cell_index(), index[1])
    view.zoom_fit()
    mw.showNormal()
    mw.raise_()
    mw.activateWindow()
    show(view, index[1], report)            # last: the browser opens on top of the main window
    return True
