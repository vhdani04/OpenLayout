"""`openlayout maestro` and `openlayout viva`.

    openlayout maestro [setup.maestro | <lib> <cell>]        the Maestro window
    openlayout maestro run <setup.maestro | <lib> <cell>> [--jobs N] [--results DIR]
    openlayout maestro new <lib> <cell>                       a maestro view for a testbench cell
    openlayout viva [file.raw ... | history-dir]              the waveform viewer
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..workarea import Workarea, WorkareaError
from .calc import fmt
from .engine import History, MaestroError, Run
from .setup import Setup, default_setup
from .vectors import VectorError


def locate(args, wa: Workarea | None):
    """(setup file, results dir) from a path or <lib> <cell>."""
    if len(args) == 1 and (args[0].endswith(".maestro") or Path(args[0]).is_file()):
        f = Path(args[0]).resolve()
        cell = wa.cell_for_path(f) if wa else None
        results = wa.run_dir(cell) / "maestro" if cell else f.parent / f"{f.stem}.results"
        return f, results
    if len(args) == 2 and wa:
        lib = wa.library(args[0])
        cell = lib.cell(args[1]) if lib else None
        if cell is None:
            raise WorkareaError(f"no cell {args[0]}/{args[1]}")
        return cell.path / f"{cell.name}.maestro", wa.run_dir(cell) / "maestro"
    raise WorkareaError("give a .maestro file, or <lib> <cell> inside a workarea")


def new_view(wa: Workarea, lib_name: str, cell_name: str) -> Path:
    lib = wa.library(lib_name)
    if lib is None:
        raise WorkareaError(f"no library {lib_name}")
    if lib.readonly:
        raise WorkareaError(f"library {lib_name} is read-only")
    cell = lib.cell(cell_name)
    if cell is None or cell.view("schematic") is None:
        raise WorkareaError(f"{lib_name}/{cell_name} has no schematic (the testbench)")
    f = cell.path / f"{cell_name}.maestro"
    if f.exists():
        raise WorkareaError(f"{f} exists")
    s = default_setup(lib_name, cell_name)
    s.save(f)
    return f


def table(h: History) -> str:
    """Outputs x points, the values with + / - for pass / fail."""
    pts = h.points
    rows = []
    names = [o["name"] for o in h.outputs] + (["vector errors"] if any("vector errors" in h.result(p["index"])
                                                                      for p in pts) else [])
    head = ["output"] + [f"{p['index']}:{p['test']} {p['label']}" for p in pts]
    rows.append(head)
    for name in names:
        row = [name]
        for p in pts:
            r = h.result(p["index"])
            e = r.get(name)
            if e is None:
                row.append("" if not r.get("_status", "done").startswith(("sim", "error")) else "sim error")
                continue
            if e.get("error"):
                row.append("err")
                continue
            v = e.get("value")
            txt = "wave" if isinstance(v, dict) and "wave" in v else fmt(v)
            row.append(txt + {True: " +", False: " -"}.get(e.get("pass"), ""))
        rows.append(row)
    widths = [max(len(r[i]) for r in rows) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows)


def summary(h: History):
    passed = failed = errors = 0
    for p in h.points:
        r = h.result(p["index"])
        if not r.get("_status", "").startswith("done"):
            errors += 1
            continue
        for k, e in r.items():
            if k.startswith("_"):
                continue
            if e.get("error"):
                errors += 1
            elif e.get("pass") is True:
                passed += 1
            elif e.get("pass") is False:
                failed += 1
    return passed, failed, errors


def run_cmd(argv):
    ap = argparse.ArgumentParser(prog="openlayout maestro run")
    ap.add_argument("target", nargs="+")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    wa = Workarea.find(".")
    f, results = locate(a.target, wa)
    if not f.is_file():
        raise WorkareaError(f"no setup {f} (openlayout maestro new <lib> <cell> creates one)")
    setup = Setup.load(f)
    if a.jobs:
        setup.jobs = a.jobs
    run = Run(setup, Path(a.results) if a.results else results, wa.root if wa else None)
    print(f"MAESTRO {f}: {len(setup.points())} point(s), results in {run.path}", flush=True)
    h = run.run(lambda done, total, msg: print(f"  [{done}/{total}] {msg}", flush=True))
    print(table(h))
    for n in h.data.get("notes", []):
        print(f"note: {n}")
    p, fl, e = summary(h)
    print(f"RESULT MAESTRO {run.name} points={len(h.points)} pass={p} fail={fl} errors={e}")
    return 0 if fl == 0 and e == 0 else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    tool = argv.pop(0) if argv and argv[0] in ("maestro", "viva") else "maestro"
    try:
        if tool == "viva":
            from ..hub.viva import main as viva_main
            return viva_main(argv)
        if argv and argv[0] == "run":
            return run_cmd(argv[1:])
        if argv and argv[0] == "new":
            wa = Workarea.find(".")
            if wa is None or len(argv) != 3:
                raise WorkareaError("openlayout maestro new <lib> <cell>, inside a workarea")
            print(f"created {new_view(wa, argv[1], argv[2])}")
            return 0
        from ..hub.maestro_window import main as gui_main
        return gui_main(argv)
    except (WorkareaError, MaestroError, VectorError, ValueError, OSError) as e:
        print(f"openlayout {tool}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
