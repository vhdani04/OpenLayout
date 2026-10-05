"""Parasitic extraction from KLayout: OpenLayout > Run PEX runs `openlayout pex` (FasterCap 3D field
solver + resistor networks, python/openlayout/pex.py) on the cell being edited - like Quantus /
xACT from Virtuoso - and writes <cell>.pex.spice next to the layout file, for post-layout
simulation.

run(): the batch run, parsed. run_current(): the menu command - the current cell as edited (saved
or not), pins in the order of its schematic when it has one.
"""
import re
import subprocess
import tempfile
from pathlib import Path

import pya

from .lvs import schematic_for

_box = None            # the (non-modal) summary of the last run
RESULT_RE = re.compile(r"^RESULT PEX \S+ devices=(\d+) resistors=(\d+) capacitors=(\d+)(.*)$", re.M)


def run(gds, cell, out, schematic=None, mode="rc"):
    """Batch PEX (as `openlayout pex`). Returns (summary dict, output text)."""
    argv = ["openlayout", "pex", str(gds), "--cell", cell, "--out", str(out), "--mode", mode]
    if schematic:
        argv += ["--schematic", str(schematic)]
    res = subprocess.run(argv, capture_output=True, text=True, timeout=7200)
    text = res.stdout + res.stderr
    m = RESULT_RE.search(text)
    if res.returncode != 0 or not m:
        raise RuntimeError(f"PEX did not run:\n{text[-800:]}")
    caps = dict(re.findall(r"C\((\S+)\)=([0-9.]+)fF", m.group(4)))
    return {"devices": int(m.group(1)), "resistors": int(m.group(2)), "capacitors": int(m.group(3)),
            "total_fF": {k: float(v) for k, v in caps.items()}, "out": str(out)}, text


def run_current(mw=None):
    """PEX of the current view's cell; returns the summary (None without a layout)."""
    mw = mw or pya.Application.instance().main_window()
    view = mw.current_view()
    cv = view.active_cellview() if view else None
    if cv is None or not cv.is_valid():
        pya.MessageBox.info("OpenLayout", "Open a layout first.", pya.MessageBox.Ok)
        return None
    cell = cv.cell_name
    tmp = Path(tempfile.mkdtemp(prefix="ol_pex_"))
    gds = tmp / f"{cell}.gds"
    cv.layout().write(str(gds))                 # the layout as edited
    out = Path(cv.filename()).parent / f"{cell}.pex.spice" if cv.filename() else tmp / f"{cell}.pex.spice"
    sch = schematic_for(cv.filename(), cell) if cv.filename() else None
    mw.message(f"PEX: extracting {cell} (FasterCap) ...", 60000)
    summary, _ = run(gds, cell, out, sch)
    caps = "\n".join(f"    {net:10s} {c:.4f} fF" for net, c in summary["total_fF"].items())
    mw.message(f"PEX {cell}: {summary['out']}", 20000)
    global _box
    _box = pya.QMessageBox(pya.QMessageBox.Information, "OpenLayout PEX",
                           f"{cell}: {summary['devices']} transistors, {summary['resistors']} resistors, "
                           f"{summary['capacitors']} capacitors\n\nTotal capacitance per pin:\n{caps}\n\n"
                           f"Netlist: {summary['out']}", pya.QMessageBox.Ok, mw)
    _box.setModal(False)
    _box.show()
    return summary
