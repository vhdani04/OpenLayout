"""Design rule check in KLayout: the ASAP7 deck (pdk/asap7/klayout/drc/asap7.drc) on the cell
being edited, results in KLayout's marker browser - like running sign-off DRC from the editor and
looking at the results in a browser.

run_current(): OpenLayout > Run DRC - checks the current cell of the current view (the layout as
edited, saved or not). show_results(): loads a report written by a batch run (`openlayout drc`,
the hub's DRC button) into the view of that layout.
"""
import os
from pathlib import Path

import pya

from . import checks

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))
DECK = FLOW / "pdk/asap7/klayout/drc/asap7.drc"


def run_current(mw=None):
    """Check the current view's cell; the results open in the marker browser. Returns the report
    database (None if there is no layout)."""
    mw = mw or pya.Application.instance().main_window()
    view = mw.current_view()
    cv = view.active_cellview() if view else None
    if cv is None or not cv.is_valid():
        pya.MessageBox.info("OpenLayout", "Open a layout first.", pya.MessageBox.Ok)
        return None
    before = view.num_rdbs()
    macro = pya.Macro(str(DECK))           # no $input / $report: this view's cell, marker browser
    mw.message(f"DRC: checking {cv.cell_name} ...", 5000)
    macro.run()
    if view.num_rdbs() <= before:
        return None
    rdb = view.rdb(view.num_rdbs() - 1)
    n = rdb.num_items()
    rules = len({item.category_id() for item in rdb.each_item()})
    mw.message(f"DRC {cv.cell_name}: " + (f"{n} violation(s)" if n else "clean"), 15000)
    checks.record(cv, "drc", n == 0, f"{n} violation(s) of {rules} rule(s)" if n else "clean")
    return rdb


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
    view.max_hier()
    view.zoom_fit()
    mw.showNormal()
    mw.raise_()
    mw.activateWindow()
    rdb = pya.ReportDatabase("DRC")
    rdb.load(str(report))
    rdb_index = view.add_rdb(rdb)
    view.show_rdb(rdb_index, index[1])      # last: the browser opens on top of the main window
    return rdb.num_items()
