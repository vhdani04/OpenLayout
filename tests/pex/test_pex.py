# Parasitic extraction (openlayout pex): library cells against the library's own reference extraction
# (Calibre xACT 3D netlists in $ASAP7_STDCELLS/CDL/xAct3D_extracted), the resistor networks, a
# hierarchical layout, the capacitance-only mode and a post-layout simulation. Run with the venv:
#   PYTHONPATH=$OPENLAYOUT_HOME/python $OPENLAYOUT_ROOT/venv/bin/python tests/pex/test_pex.py
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import klayout.db as kdb

from openlayout import fieldsolver, pex

STD = Path(os.environ["ASAP7_STDCELLS"])
LIB_GDS = STD / "GDS" / "asap7sc7p5t_28_R_220121a.gds"
XACT = STD / "CDL" / "xAct3D_extracted" / "asap7sc7p5t_28_R.sp"
TMP = Path(tempfile.mkdtemp(prefix="ol_test_pex_"))
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def xact_totals(cell):
    """Total capacitance (F) per net of `cell` in the reference: the ground capacitances of its
    PM_<cell>%<net> subcircuits plus the cc_ couplings."""
    text = XACT.read_text().replace("\n+", " ")
    unit = {"f": 1e-15, "a": 1e-18, "p": 1e-12}

    def val(s):
        m = re.match(r"([0-9.eE+-]+)([fap]?)", s)
        return float(m.group(1)) * unit.get(m.group(2), 1.0)

    tot = defaultdict(float)
    pm = inside = None
    for line in text.splitlines():
        t = line.split()
        if not t:
            continue
        if t[0].lower() == ".subckt":
            m = re.match(rf"PM_{re.escape(cell)}%(\S+)$", t[1])
            pm, inside = (m.group(1) if m else None), t[1] == cell
        elif t[0].lower() == ".ends":
            pm = inside = None
        elif pm and t[0].lower().startswith("c") and len(t) >= 4:
            tot[pm] += val(t[3])
        elif inside and t[0].lower().startswith("cc") and len(t) >= 4:
            for node in t[1:3]:
                m = re.match(r"N_(.+?)_\d+$", node)
                tot[m.group(1) if m else node] += val(t[3])
    return tot


def netlist(path):
    lines = Path(path).read_text().splitlines()
    sub = next(l for l in lines if l.startswith(".subckt"))
    return lines, sub.split()[2:]


# ---- the field solver: a parallel-plate capacitor, one and two dielectrics -------------------------
# 1 x 1 um plates 100 nm apart; k = 4 in the lowest 20 nm and 1 above: series plates give
# eps0 / (0.02 / 4 + 0.08) = 1.04e-16 F, the other way round 2.21e-16 F (plus some 15-25 % fringe)
sq = kdb.Region(kdb.Box(0, 0, 1000, 1000))
plates = {"top": [(sq, 0.1, 0.1)], "bottom": [(sq, 0.0, 0.0)]}
win = kdb.Box(-1000, -1000, 2000, 2000)
c1 = -fieldsolver.capacitance_matrix(plates, 0.001, 1.0, TMP / "plate1", (), win, 0.1)[1][0][1]
c41 = -fieldsolver.capacitance_matrix(plates, 0.001, 4.0, TMP / "plate41", [(0.02, 1.0)], win, 0.1)[1][0][1]
c14 = -fieldsolver.capacitance_matrix(plates, 0.001, 1.0, TMP / "plate14", [(0.02, 4.0)], win, 0.1)[1][0][1]
check(f"field solver: plates {c1:.3g} F in vacuum (8.85e-17 + fringe)", 1.0 < c1 / 8.854e-17 < 1.3)
check(f"field solver: dielectric layers {c41:.3g} / {c14:.3g} F (1.04e-16 / 2.21e-16 + fringe)",
      1.0 < c41 / 1.0417e-16 < 1.35 and 1.0 < c14 / 2.2135e-16 < 1.3)

# ---- library cells against the reference ----------------------------------------------------------
# (the front end is calibrated on these cells and more: inputs come within a few %, single-stage
# outputs some 5-15 % under xACT 3D - docs/PEX.md)
for cell, pins in (("INVx1", ["A", "Y"]), ("NAND2xp33", ["A", "B", "Y"])):
    name = f"{cell}_ASAP7_75t_R"
    out = TMP / f"{cell}.pex.spice"
    s = pex.extract(LIB_GDS, name, out)
    ref = xact_totals(name)
    lines, order = netlist(out)
    for p in pins:
        ours, theirs = s["total_fF"][p], ref[p] * 1e15
        lo, hi = (0.90, 1.10) if p != "Y" else (0.80, 1.10)
        check(f"{cell} C({p}) {ours:.3f} fF vs xACT 3D {theirs:.3f} fF", lo <= ours / theirs <= hi)
    devs = [l for l in lines if l.startswith("N")]
    check(f"{cell}: {len(devs)} transistors, BSIM-CMG cards", len(devs) == (2 if cell == "INVx1" else 4)
          and all(re.search(r" [np]mos_rvt l=20n nfin=\d+$", l) for l in devs), devs[:1])
    check(f"{cell}: pins in the CDL order", order == (["A", "VDD", "VSS", "Y"] if cell == "INVx1"
                                                     else ["A", "B", "VDD", "VSS", "Y"]), order)
    rs = [l for l in lines if l.startswith("R")]
    check(f"{cell}: resistor networks on the signal nets, supplies ideal",
          rs and all(float(l.split()[3]) > 0 for l in rs) and not any(re.search(r" VDD_|VSS_", l) for l in lines))

# the gate of INVx1: pin -> LIG -> gate -> both channels, some 25-60 Ohm (7.1 Ohm/sq gate, 20 nm wide)
lines, _ = netlist(TMP / "INVx1.pex.spice")
gate_r = [float(l.split()[3]) for l in lines if l.startswith("R") and " A" in l]
check("INVx1: the input network reaches both gates", len(gate_r) >= 3 and all(5 < r < 100 for r in gate_r), gate_r)
# the output: source / drain -> V0 -> M1 to the pin, 40-50 Ohm in xACT 3D; OpenROAD's M1 is ~3x lower
out_r = [float(l.split()[3]) for l in lines if l.startswith("R") and " Y" in l]
pex.extract(LIB_GDS, "INVx1_ASAP7_75t_R", TMP / "INVx1_orfs.spice", rmodel="openroad")
lines_o, _ = netlist(TMP / "INVx1_orfs.spice")
out_o = [float(l.split()[3]) for l in lines_o if l.startswith("R") and " Y" in l]
check("INVx1: output network like xACT 3D's; --rmodel openroad lower", out_r and all(35 < r < 90 for r in out_r)
      and max(out_o) < min(out_r), (out_r, out_o))

# ---- a hierarchical layout: a placed INVx1 under labels of its own ---------------------------------
lib = kdb.Layout()
lib.read(str(LIB_GDS))
src = lib.cell("INVx1_ASAP7_75t_R")
ly = kdb.Layout()
ly.dbu = lib.dbu
inv = ly.create_cell("INVx1_ASAP7_75t_R")
for li in lib.layer_indexes():
    inv.shapes(ly.layer(lib.get_info(li))).insert(src.shapes(li))
top = ly.create_cell("myinv")
top.insert(kdb.DCellInstArray(inv.cell_index(), kdb.DTrans(1.0, 0.5)))
rename = {"A": "IN", "Y": "OUT", "VDD": "VDD", "VSS": "VSS"}
for li in ly.layer_indexes():
    for sh in inv.shapes(li).each():
        if sh.is_text() and sh.text_string in rename:
            t = sh.dtext.moved(1.0, 0.5)
            t.string = rename[sh.text_string]
            top.shapes(li).insert(t)
gds = TMP / "myinv.gds"
ly.write(str(gds))
s = pex.extract(gds, "myinv")
lines, order = netlist(TMP / "myinv.pex.spice")
check("hierarchy: flattened, the top's labels are the pins", sorted(order) == ["IN", "OUT", "VDD", "VSS"]
      and len([l for l in lines if l.startswith("N")]) == 2, order)
inv1 = pex.extract(LIB_GDS, "INVx1_ASAP7_75t_R", TMP / "inv_again.spice")
check("hierarchy: same capacitances as the cell itself",
      abs(s["total_fF"]["IN"] - inv1["total_fF"]["A"]) < 0.02 * inv1["total_fF"]["A"])
s = pex.extract(gds, "myinv", TMP / "myinv_c.spice", mode="c")
lines, _ = netlist(TMP / "myinv_c.spice")
check("--mode c: capacitances only", s["resistors"] == 0 and s["capacitors"] > 0
      and not any(l.startswith("R") for l in lines))

# ---- post-layout simulation: FO2 inverter, schematic vs extracted -------------------------------
(TMP / "pre.spice").write_text(".subckt INVT A VDD VSS Y\nN1 Y A VSS VSS nmos_rvt l=20n nfin=3\n"
                               "N2 Y A VDD VDD pmos_rvt l=20n nfin=3\n.ends\n")
(TMP / "post.spice").write_text((TMP / "INVx1.pex.spice").read_text().replace("INVx1_ASAP7_75t_R", "INVT"))
delay = {}
for v in ("pre", "post"):
    (TMP / f"tb_{v}.sp").write_text(f"""* FO2 inverter delay ({v}-layout)
.lib asap7.lib tt
.include {TMP / (v + '.spice')}
Vdd vdd 0 0.7
Vss vss 0 0
Vin a 0 pulse(0 0.7 20p 10p 10p 60p 140p)
X1 a vdd vss y INVT
X2 y vdd vss z1 INVT
X3 y vdd vss z2 INVT
.tran 0.1p 160p
.meas tran tphl trig v(a) val=0.35 rise=1 targ v(y) val=0.35 fall=1
.end
""")
    res = subprocess.run(["ngspice", "-b", f"tb_{v}.sp"], cwd=TMP, capture_output=True, text=True, timeout=300)
    m = re.search(r"^tphl\s*=\s*([0-9.eE+-]+)", res.stdout, re.M)
    delay[v] = float(m.group(1)) if m else None
ok = delay["pre"] and delay["post"] and 1.1 < delay["post"] / delay["pre"] < 2.5
check("post-layout simulation: the parasitics slow the inverter down",
      ok, f"{(delay['pre'] or 0) * 1e12:.2f} ps -> {(delay['post'] or 0) * 1e12:.2f} ps")

if failures:
    print(f"FAIL pex: {len(failures)} check(s) failed")
    sys.exit(1)
print("PASS pex")
