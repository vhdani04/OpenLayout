"""Windowed PEX of an array against one flat solve: a cell tiled into rows x cols (odd rows mirrored
about the shared rail, as in an SRAM array), extracted both ways, the total capacitance per net and
the times compared.

  windows.py <cell.gds> <cell> <rows> <cols> [--flat] [--out DIR] [--halo UM]

  PYTHONPATH=$OPENLAYOUT_HOME/python $OPENLAYOUT_ROOT/venv/bin/python tests/pex/bench/windows.py \\
      SRAMCIMsbc.gds SRAMCIMsbc 4 8 --flat

Without --flat only the windowed extraction runs (a flat solve of more than ~200 nets takes hours).
Net names other than the labels are not the same from one extraction to the next, so the
unlabelled nets are compared as sorted lists. Run it under `nice` on a machine in use: FasterCap
takes a whole core.
"""
import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

import klayout.db as kdb

from openlayout import pex


def tile(src, cell, rows, cols, out):
    """`cell` of `src` placed rows x cols at its pitch (odd rows mirrored), its labels on the top."""
    ly = kdb.Layout()
    ly.read(str(src))
    c = ly.cell(cell)
    w = c.dbbox().width()
    h = c.dbbox().height() - 2 * max(0.0, -c.dbbox().bottom)        # the rails' pitch, not their overhang
    top = ly.create_cell(f"{cell}_{rows}x{cols}")
    for r in range(rows):
        for k in range(cols):
            t = kdb.DTrans(k * w, r * h) if r % 2 == 0 else kdb.DTrans(kdb.DTrans.M0, kdb.DVector(k * w, (r + 1) * h))
            top.insert(kdb.DCellInstArray(c.cell_index(), t))
    for li in ly.layer_indexes():
        for s in c.shapes(li).each():
            if s.is_text():
                top.shapes(li).insert(s.dtext)
    opt = kdb.SaveLayoutOptions()
    opt.select_cell(top.cell_index())
    ly.write(str(out), opt)
    return top.name


def compare(flat, win):
    a, b = flat["all_fF"], win["all_fF"]
    named = sorted(n for n in a if not n.startswith("net") and n in b)
    for n in named:
        print(f"  {n:10s} flat {a[n]:8.4f} fF  windowed {b[n]:8.4f} fF  {(b[n] / a[n] - 1) * 100:+6.2f} %")
    ua = sorted(v for n, v in a.items() if n.startswith("net"))
    ub = sorted(v for n, v in b.items() if n.startswith("net"))
    e = [(y / x - 1) * 100 for x, y in zip(ua, ub)]
    sig = [(b[n] / a[n] - 1) * 100 for n in named if not pex.POWER_RE.match(n)] + e
    if e:
        print(f"  {len(e)} unlabelled nets: mean |error| {statistics.mean(map(abs, e)):.2f} %, max {max(map(abs, e)):.2f} %")
    print(f"  signal nets: mean |error| {statistics.mean(map(abs, sig)):.2f} %, max {max(map(abs, sig)):.2f} %")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gds")
    ap.add_argument("cell")
    ap.add_argument("rows", type=int)
    ap.add_argument("cols", type=int)
    ap.add_argument("--flat", action="store_true", help="also one flat solve, to compare with")
    ap.add_argument("--out", help="directory for the layout and netlists (default: a temporary one)")
    ap.add_argument("--halo", type=float, default=pex.WIN_HALO)
    a = ap.parse_args()
    out = Path(a.out or tempfile.mkdtemp(prefix="ol_pexwin_"))
    out.mkdir(parents=True, exist_ok=True)
    gds = out / f"{a.cell}_{a.rows}x{a.cols}.gds"
    top = tile(a.gds, a.cell, a.rows, a.cols, gds)
    res = {}
    for cap in (["flat"] if a.flat else []) + ["window"]:
        t = time.time()
        res[cap] = pex.extract(gds, top, out / f"{top}.{cap}.pex.spice", cap=cap, halo=a.halo, cache=False)
        print(f"{cap}: {time.time() - t:.0f} s, {res[cap]['capacitors']} capacitors"
              + (f", windows {res[cap]['windows']}" if res[cap]["windows"] else ""), flush=True)
    if a.flat:
        compare(res["flat"], res["window"])
    print(f"netlists in {out}")


if __name__ == "__main__":
    sys.exit(main())
