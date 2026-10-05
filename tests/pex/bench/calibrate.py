"""Calibrate the front end of the PEX process description (pdk/asap7/klayout/pex/gen_pex_tech.py,
CALIBRATED) against the library's reference extraction netlists: the total capacitance of every pin and
the couplings between pins of a set of cells, scored as the RMS of the log errors (couplings at
half weight). Runs the real pipeline (pex.capacitance on gen_pex_tech.build(params)).

  calibrate.py eval '{"k_feol": 4.6}' [cells]     one evaluation, per-pin table
  calibrate.py fit  '{start}' [cells]              coordinate search (KEYS=k_feol,sti_depth,...  ROUNDS=3)

  PYTHONPATH=$OPENLAYOUT_HOME/python $OPENLAYOUT_ROOT/venv/bin/python tests/pex/bench/calibrate.py ...

Minutes per evaluation (about 1.5 s per cell); a fit is an hour or so.
"""
import importlib.util
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from openlayout import pex  # noqa: E402
import bench  # noqa: E402

spec = importlib.util.spec_from_file_location("gen_pex_tech", pex.FLOW / "pdk/asap7/klayout/pex/gen_pex_tech.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

FIT_CELLS = ["INVx1", "INVx4", "BUFx2", "NAND2xp33", "NOR2xp33", "AOI21xp33", "XOR2xp5", "AND2x2"]
STEPS = {"gate_top": 0.008, "sti_depth": 0.0075, "sd_gap": 0.00025, "mol_top": 0.008, "k_feol": 0.3}
LIMITS = {"gate_top": (0.0, 0.06), "sti_depth": (0.002, 0.3), "sd_gap": (0.00025, 0.004),
          "mol_top": (0.04, 0.12), "k_feol": (3.0, 9.0)}
WORK = Path(tempfile.mkdtemp(prefix="ol_calib_"))


class Cell:
    def __init__(self, name):
        self.name, self.full = name, name + bench.SUF
        self.lvsdb = pex.extract_netlist(bench.GDS, self.full, WORK)
        self.ref, self.refc = bench.xact_caps(self.full)

    def rows(self, tech):
        ground, coupling = pex.capacitance(self.lvsdb, self.full, WORK / self.name, tech, "VSS")
        total = dict(ground)
        for (a, b), c in coupling.items():
            total[a] = total.get(a, 0) + c
            total[b] = total.get(b, 0) + c
        pins = [n for n in total if n in self.ref and not n.upper().startswith(("VDD", "VSS"))]
        out = [("total", f"{self.name}.{n}", total[n], self.ref[n]) for n in pins]
        for (a, b), c in self.refc.items():
            if a in pins and b in pins:
                out.append(("coupling", f"{self.name}.{a}-{b}", coupling.get((a, b), coupling.get((b, a), 0)), c))
        return out


_seen = {}


def evaluate(p, cells, verbose=False):
    key = json.dumps(p, sort_keys=True)
    if key in _seen and not verbose:
        return _seen[key]
    t0 = time.time()
    tech = gen.build(p)
    rows = [r for c in cells for r in c.rows(tech)]
    tot = [math.log(o / r) for k, _, o, r in rows if k == "total" and o > 0]
    cou = [math.log(o / r) for k, _, o, r in rows if k == "coupling" and o > 0 and r > 2e-18]
    rms = math.sqrt(sum(e * e for e in tot) / len(tot))
    score = rms + 0.5 * math.sqrt(sum(e * e for e in cou) / max(1, len(cou)))
    if verbose:
        for k, lab, o, r in rows:
            print(f"  {k:8s} {lab:22s} {o * 1e15:7.4f} {r * 1e15:7.4f} {(o / r - 1) * 100:+6.1f}%")
    print(f"score {score:.4f}  totals rms {rms * 100:.1f}% mean {sum(tot) / len(tot) * 100:+.1f}%  couplings mean "
          f"{sum(cou) / max(1, len(cou)) * 100:+.1f}%  ({time.time() - t0:.0f} s)  {json.dumps(p)}", flush=True)
    _seen[key] = score
    return score


def fit(p, cells, keys, rounds=3):
    best = evaluate(p, cells)
    steps = {k: STEPS[k] for k in keys}
    for r in range(rounds):
        for k in keys:
            for sign in (1, -1):
                while True:
                    q = dict(p)
                    q[k] = round(min(max(p[k] + sign * steps[k], LIMITS[k][0]), LIMITS[k][1]), 6)
                    if q[k] == p[k] or q["mol_top"] - 0.027 <= 0.002 or q["mol_top"] <= q["gate_top"] + 0.01:
                        break
                    s = evaluate(q, cells)
                    if s >= best - 1e-4:
                        break
                    best, p = s, q
        steps = {k: v / 2 for k, v in steps.items()}
        print(f"round {r} best {best:.4f} {json.dumps(p)}", flush=True)
    return p


if __name__ == "__main__":
    mode = sys.argv[1]
    p = dict(gen.CALIBRATED)
    if len(sys.argv) > 2 and sys.argv[2]:
        p.update(json.loads(sys.argv[2]))
    cells = [Cell(n) for n in (sys.argv[3:] or FIT_CELLS)]
    if mode == "eval":
        evaluate(p, cells, verbose=True)
    elif mode == "fit":
        fit(p, cells, os.environ.get("KEYS", "k_feol,sti_depth,sd_gap,gate_top,mol_top").split(","),
            int(os.environ.get("ROUNDS", 3)))
