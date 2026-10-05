"""The hub's Checks list for checks run in KLayout (OpenLayout > Run DRC / LVS / PEX): the result
goes to the running hub, which records it and refreshes the Library Manager; without a hub it is
written to the workarea's state file directly (the hub shows it when it starts).
"""
import subprocess
from pathlib import Path

from .generate import _workarea


def record(cv, step, ok, detail):
    """Record `step` ("drc", "lvs", "pex") of the cellview's cell. Returns where it went: "hub",
    "workarea" or None (the layout is not part of a workarea)."""
    path = cv.filename() if cv is not None and cv.is_valid() else ""
    if not path:
        return None
    argv = ["openlayout", "hubcmd", "checked", path, "--cell", cv.cell_name, "--step", step, "--detail", detail]
    if ok:
        argv.append("--ok")
    try:
        if subprocess.run(argv, capture_output=True, text=True, timeout=10).returncode == 0:
            return "hub"
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        Workarea = _workarea()
        wa = Workarea.find(Path(path).parent)
        cell = wa.cell_for_path(path, cv.cell_name) if wa else None
        if cell is None:
            return None
        wa.set_state(cell, step, ok, detail)
        return "workarea"
    except Exception as e:                  # never let the bookkeeping break a check
        print(f"OpenLayout: could not record the {step} result: {e}")
        return None
