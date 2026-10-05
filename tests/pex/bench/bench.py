"""PEX benchmark against the library's Calibre xACT 3D netlists ($ASAP7_STDCELLS/CDL/xAct3D_extracted).

  bench.py caps  [cells...]     total capacitance per pin, ours vs xACT 3D, and the PEX time
  bench.py delay [cells...]     FO2 delays of a set of arcs: schematic / xACT 3D / ours (ngspice)
  bench.py all   [cells...]     both (default cells: CELLS, BENCH_SUBSET=1 for a short list)

  PYTHONPATH=$OPENLAYOUT_HOME/python $OPENLAYOUT_ROOT/venv/bin/python tests/pex/bench/bench.py all

Env: BENCH_OUT (results, default a temporary directory), BENCH_TAG (results file names),
BENCH_TECH (another asap7_pex.json). About 6 s per cell; the full list takes some 6 minutes.
xACT 3D extracts nothing on unlabelled internal nets (noxref_*), so arcs through a stack node
(AOI21 A1->Y, OAI21 B->Y, XOR2 B->Y) come out slower with OpenLayout's extraction.
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from openlayout import pex  # noqa: E402

STD = Path(os.environ["ASAP7_STDCELLS"])
GDS = STD / "GDS" / "asap7sc7p5t_28_R_220121a.gds"
XACT = STD / "CDL" / "xAct3D_extracted" / "asap7sc7p5t_28_R.sp"
CDL = STD / "CDL" / "LVS" / "asap7sc7p5t_28_R.cdl"
OUT = Path(os.environ.get("BENCH_OUT") or tempfile.mkdtemp(prefix="ol_bench_"))
OUT.mkdir(parents=True, exist_ok=True)
SUF = "_ASAP7_75t_R"

CELLS = ["INVxp33", "INVxp67", "INVx1", "INVx2", "INVx3", "INVx4", "INVx5", "INVx6", "INVx8", "INVx11",
         "BUFx2", "BUFx3", "BUFx4", "BUFx6f", "BUFx10", "NAND2xp33", "NAND2xp5", "NAND2xp67", "NAND2x1",
         "NAND2x2", "NAND3xp33", "NAND3x1", "NAND4xp25", "NOR2xp33", "NOR2xp67", "NOR2x1", "NOR2x2",
         "NOR3xp33", "AND2x2", "AND3x1", "AND4x1", "OR2x2", "OR3x1", "AOI21xp33", "AOI21xp5", "AOI21x1",
         "AOI22xp33", "AOI22x1", "OAI21xp33", "OAI21x1", "OAI22xp33", "XOR2xp5", "XOR2x1", "XNOR2xp5",
         "MAJIxp5", "FAx1", "HAxp5", "DFFHQNx1", "DHLx1", "ICGx1", "TIEHIx1", "A2O1A1Ixp33", "O2A1O1Ixp33",
         "SDFHx1", "DECAPx2"]
SUBSET = ["INVx1", "INVx4", "BUFx2", "NAND2xp33", "NAND2x1", "NOR2xp33", "AOI21xp33", "OAI21xp33",
          "XOR2xp5", "AND2x2", "MAJIxp5", "DFFHQNx1"]

# delay arcs: cell -> [(input, {side input: level}, output)]
ARCS = {
    "INVx1": [("A", {}, "Y")], "INVx4": [("A", {}, "Y")], "INVxp33": [("A", {}, "Y")],
    "BUFx2": [("A", {}, "Y")], "BUFx4": [("A", {}, "Y")],
    "NAND2xp33": [("A", {"B": 1}, "Y"), ("B", {"A": 1}, "Y")], "NAND2x1": [("A", {"B": 1}, "Y")],
    "NOR2xp33": [("A", {"B": 0}, "Y"), ("B", {"A": 0}, "Y")], "NOR2x1": [("A", {"B": 0}, "Y")],
    "AND2x2": [("A", {"B": 1}, "Y")], "OR2x2": [("A", {"B": 0}, "Y")],
    "NAND3xp33": [("A", {"B": 1, "C": 1}, "Y")],
    "AOI21xp33": [("A1", {"A2": 1, "B": 0}, "Y"), ("B", {"A1": 0, "A2": 0}, "Y")],
    "OAI21xp33": [("A1", {"A2": 0, "B": 1}, "Y"), ("B", {"A1": 1, "A2": 1}, "Y")],
    "XOR2xp5": [("A", {"B": 0}, "Y"), ("B", {"A": 1}, "Y")],
    "MAJIxp5": [("A", {"B": 1, "C": 0}, "Y")],
}


# ---- reference ------------------------------------------------------------------------------------
_xact = None


def xact_subckts():
    global _xact
    if _xact is None:
        text = XACT.read_text().replace("\n+", " ")
        subs, cur = {}, None
        for line in text.splitlines():
            t = line.split()
            if not t or line.startswith("*"):
                continue
            if t[0].lower() == ".subckt":
                cur = t[1]
                subs[cur] = (t[2:], [])
            elif t[0].lower() == ".ends":
                cur = None
            elif cur:
                subs[cur][1].append(line.split(" $")[0].split("\t$")[0].strip())
        _xact = subs
    return _xact


def val(s):
    m = re.match(r"([0-9.eE+-]+)([fap]?)", s)
    return float(m.group(1)) * {"f": 1e-15, "a": 1e-18, "p": 1e-12}.get(m.group(2), 1.0)


def xact_caps(cell):
    """{net: total C}, {(a, b): coupling} of the reference (pins and internal nets)."""
    subs = xact_subckts()
    tot, coup = defaultdict(float), defaultdict(float)
    for name, (ports, lines) in subs.items():
        m = re.match(rf"PM_{re.escape(cell)}%(\S+)$", name)
        if m:
            for l in lines:
                t = l.split()
                if t[0].lower().startswith("c"):
                    tot[m.group(1)] += val(t[3])
    for l in subs[cell][1]:
        t = l.split()
        if t[0].lower().startswith("cc"):
            a, b = (re.match(r"N_(.+?)_\d+$", x) for x in t[1:3])
            a, b = a.group(1) if a else t[1], b.group(1) if b else t[2]
            c = val(t[3])
            tot[a] += c
            tot[b] += c
            coup[tuple(sorted((a, b)))] += c
    return dict(tot), dict(coup)


def xact_spice(cell, new):
    """The reference netlist of `cell` for ngspice, subcircuit renamed `new`."""
    subs = xact_subckts()

    def ren(n):
        return re.sub(r"[^A-Za-z0-9_]", "_", n.replace(f"PM_{cell}%", f"PMX_{new}_"))

    out = []
    names = [n for n in subs if n.startswith(f"PM_{cell}%")] + [cell]
    for n in names:
        ports, lines = subs[n]
        out.append(f".subckt {new if n == cell else ren(n)} {' '.join(ports)}")
        for l in lines:
            t = l.split()
            k = t[0][0].lower()
            if k == "m":
                params = {p.split("=")[0].lower(): p.split("=")[1] for p in t[6:] if "=" in p}
                out.append(f"N{t[0]} {' '.join(t[1:5])} {t[5]} l={params['l']} nfin={params['nfin']}")
            elif k == "r":                  # ngspice + OSDI fail on the 1e-5 Ohm shorts xACT writes
                out.append(f"{t[0]} {t[1]} {t[2]} {max(val(t[3]), 1e-3):g}")
            elif k == "c":
                out.append(" ".join(t[:4]))
            elif k == "x":
                out.append(f"{ren(t[0])} {' '.join(t[1:-1])} {ren(t[-1])}")
        out.append(".ends")
    return "\n".join(out) + "\n", subs[cell][0]


# ---- ours -----------------------------------------------------------------------------------------
def ours(cell, tech=None):
    if tech:
        pex.TECH_JSON = Path(tech)
    out = OUT / f"{cell}.pex.spice"
    t0 = time.time()
    s = pex.extract(GDS, cell, out)
    s["seconds"] = time.time() - t0
    return s


def caps(cells):
    rows, t_all = [], 0.0
    for c in cells:
        cell = c + SUF
        if cell not in xact_subckts():
            print(f"  (no reference for {c})")
            continue
        s = ours(cell, os.environ.get("BENCH_TECH"))
        t_all += s["seconds"]
        ref, _ = xact_caps(cell)
        for pin, v in s["total_fF"].items():
            if pin.upper().startswith(("VDD", "VSS")) or pin not in ref:
                continue
            rows.append((c, pin, v, ref[pin] * 1e15, s["seconds"]))
    return rows, t_all


def report_caps(rows, t_all, kind_of):
    print(f"\n{'cell':14s} {'pin':5s} {'ours':>8s} {'xACT':>8s} {'err':>7s}")
    errs = defaultdict(list)
    for c, pin, v, r, _ in rows:
        e = v / r - 1
        errs[kind_of(c, pin)].append(e)
        print(f"{c:14s} {pin:5s} {v:8.4f} {r:8.4f} {e * 100:+6.1f}%")
    print()
    for k, es in sorted(errs.items()):
        mean = sum(es) / len(es)
        rms = math.sqrt(sum(e * e for e in es) / len(es))
        print(f"{k:7s} n={len(es):3d}  mean {mean * 100:+6.1f}%  rms {rms * 100:5.1f}%  "
              f"min {min(es) * 100:+6.1f}%  max {max(es) * 100:+6.1f}%")
    print(f"total PEX time {t_all:.0f} s")


# ---- delay ----------------------------------------------------------------------------------------
def cdl_ports(cell):
    text = CDL.read_text()
    m = re.search(rf"^\.SUBCKT\s+{re.escape(cell)}\s+(.*)$", text, re.M | re.I)
    return m.group(1).split()


def inst(name, sub, ports, conn):
    return f"{name} " + " ".join(conn.get(p, conn.get(p.upper(), f"nc_{name}_{p}")) for p in ports) + f" {sub}"


def delay(cells):
    res = []
    for c in cells:
        if c not in ARCS:
            continue
        cell = c + SUF
        work = Path(tempfile.mkdtemp(prefix="bench_d_", dir=OUT))
        xsp, xports = xact_spice(cell, f"{c}_XACT")
        (work / "xact.sp").write_text(xsp)
        ol = OUT / f"{cell}.pex.spice"
        if not ol.is_file():
            ours(cell, os.environ.get("BENCH_TECH"))
        text = ol.read_text().replace(f".subckt {cell} ", f".subckt {c}_OL ")
        (work / "ol.sp").write_text(text)
        olports = re.search(rf"^\.subckt {c}_OL (.*)$", text, re.M).group(1).split()
        sch_ports = cdl_ports(cell)
        for inp, side, outp in ARCS[c]:
            row = {"cell": c, "arc": f"{inp}->{outp}"}
            for v, sub, ports in (("sch", cell, sch_ports), ("xact", f"{c}_XACT", xports), ("ol", f"{c}_OL", olports)):
                conn = {"VDD": "vdd", "VSS": "0", inp: "in", outp: "out"}
                lines = ["* delay", ".lib asap7.lib tt", f".include {work}/xact.sp", f".include {work}/ol.sp",
                         "Vdd vdd 0 0.7", "Vin in 0 pwl(0 0 20p 0 32p 0.7 120p 0.7 132p 0)"]
                for k, (p, lvl) in enumerate(side.items()):
                    conn[p] = f"s{k}"
                    lines.append(f"Vs{k} s{k} 0 {0.7 if lvl else 0}")
                lines.append(inst("X0", sub, ports, conn))
                for k in range(2):           # FO2: library INVx1 (schematic; ports A VDD VSS Y)
                    lines.append(f"XL{k} out vdd 0 nl{k} INVx1{SUF}")
                lines += [".tran 0.05p 220p",
                          ".meas tran d1 trig v(in) val=0.35 rise=1 targ v(out) val=0.35 cross=1",
                          ".meas tran d2 trig v(in) val=0.35 fall=1 targ v(out) val=0.35 cross=2", ".end"]
                (work / f"tb_{v}.sp").write_text("\n".join(lines) + "\n")
                r = subprocess.run(["ngspice", "-b", f"tb_{v}.sp"], cwd=work, capture_output=True, text=True)
                d = [re.search(rf"^{k}\s*=\s*([0-9.eE+-]+)", r.stdout, re.M) for k in ("d1", "d2")]
                row[v] = [float(x.group(1)) * 1e12 if x else float("nan") for x in d]
                if not all(d):
                    row[v + "_err"] = r.stdout[-300:] + r.stderr[-300:]
            res.append(row)
    return res


def report_delay(res):
    print(f"\n{'cell':12s} {'arc':6s} {'sch':>12s} {'xACT':>12s} {'ours':>12s} {'err vs xACT':>13s} {'parasitic captured':>19s}")
    es, caps_ = [], []
    for r in res:
        line = f"{r['cell']:12s} {r['arc']:6s}"
        for v in ("sch", "xact", "ol"):
            line += f" {r[v][0]:5.2f}/{r[v][1]:5.2f}"
        e = [o / x - 1 for o, x in zip(r["ol"], r["xact"])]
        p = [(o - s) / (x - s) for o, x, s in zip(r["ol"], r["xact"], r["sch"])]
        es += e
        caps_ += p
        line += f"  {e[0] * 100:+5.1f}/{e[1] * 100:+5.1f}%  {p[0] * 100:5.0f}/{p[1] * 100:4.0f}%"
        print(line)
        for v in ("sch", "xact", "ol"):
            if r.get(v + "_err"):
                print("   ", v, r[v + "_err"])
    es = [e for e in es if e == e]
    caps_ = [p for p in caps_ if p == p]
    if es:
        print(f"delay error vs xACT: mean {sum(es) / len(es) * 100:+.1f}%  rms "
              f"{math.sqrt(sum(e * e for e in es) / len(es)) * 100:.1f}%; parasitic delay captured: "
              f"mean {sum(caps_) / len(caps_) * 100:.0f}%")


def kind_of(c, pin):
    return "output" if pin in ("Y", "QN", "Q", "CON", "SN", "GCLK") else "input"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    cells = sys.argv[2:] or (SUBSET if os.environ.get("BENCH_SUBSET") else CELLS)
    tag = os.environ.get("BENCH_TAG", "run")
    if mode in ("caps", "all"):
        rows, t = caps(cells)
        report_caps(rows, t, kind_of)
        json.dump(rows, open(OUT / f"caps_{tag}.json", "w"))
    if mode in ("delay", "all"):
        res = delay([c for c in cells if c in ARCS])
        report_delay(res)
        json.dump(res, open(OUT / f"delay_{tag}.json", "w"))
