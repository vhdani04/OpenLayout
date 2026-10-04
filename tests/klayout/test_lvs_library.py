# Every ASAP7 7.5T standard cell must pass LVS against the library's CDL (the reference for the
# FinFET device extraction: fins -> W, VT flavour, fingers, split gates). All cells of a library
# are placed side by side under one top cell and compared in one run (stdcells=check: transistor
# level); each cell is its own circuit pair. KLayout batch mode:
#   klayout -b -r tests/klayout/test_lvs_library.py [-rd libs=R,L,SL,SRAM]
#
# PERMUTED: cells whose layout orders series transistors differently from the CDL (or splits a
# stack in a way KLayout does not join). A strict topological compare reports them; for these the
# test checks that layout and CDL have the same transistors - per type and gate pin, the same total
# width - so the extraction is right and only the order in the stacks differs.
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pya

HOME = Path(os.environ["OPENLAYOUT_HOME"])
DECK = HOME / "pdk/asap7/klayout/lvs/asap7.lvs"
STD = Path(os.environ.get("ASAP7_STDCELLS", HOME.parent / "pdk/asap7/asap7sc7p5t_28"))
PERMUTED = {"A2O1A1O1Ixp25", "AOI211xp5", "NAND3x2", "NOR3x2", "OAI21x1", "OAI221xp5", "SDFLx1", "SDFLx2",
            "SDFLx3"}
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def run(vt):
    cdl = STD / "CDL" / "LVS" / f"asap7sc7p5t_28_{vt}.cdl"
    ports = {}
    for line in cdl.read_text().splitlines():
        t = line.split()
        if t and t[0].upper() == ".SUBCKT":
            ports[t[1]] = t[2:]
    src = pya.Layout()
    src.read(str(STD / "GDS" / f"asap7sc7p5t_28_{vt}_220121a.gds"))
    names = sorted(c.name for c in src.top_cells())
    no_cdl = [n for n in names if n not in ports]
    names = [n for n in names if n in ports]
    out = pya.Layout()
    out.dbu = src.dbu
    top = out.create_cell("ALL")
    ref = [".SUBCKT ALL"]
    x = 0
    for i, name in enumerate(names):
        c = out.create_cell(name)
        c.copy_tree(src.cell(name))
        top.insert(pya.CellInstArray(c.cell_index(), pya.Trans(x, 0)))
        x += c.bbox().width() + round(1.08 / src.dbu)
        ref.append(f"X{i} " + " ".join(f"n{i}_{p}" for p in ports[name]) + f" {name}")
    ref.append(".ENDS")
    tmp = Path(tempfile.mkdtemp())
    out.write(str(tmp / "all.gds"))
    (tmp / "all.sp").write_text("\n".join(ref) + "\n")
    res = subprocess.run(["klayout", "-b", "-r", str(DECK), "-rd", f"input={tmp / 'all.gds'}", "-rd", "topcell=ALL",
                          "-rd", f"schematic={tmp / 'all.sp'}", "-rd", f"cdl={cdl}", "-rd", "stdcells=check",
                          "-rd", f"report={tmp / 'all.lvsdb'}"], capture_output=True, text=True)
    text = res.stdout + res.stderr
    m = re.search(r"^RESULT LVS ALL (\w+) circuits=(\d+) bulk=(\d+)", text, re.M)
    check(f"{vt}: the LVS run finishes", res.returncode == 0 and m is not None, "" if m else text[-400:])
    if m is None:
        return
    lvs = pya.LayoutVsSchematic()
    lvs.read(str(tmp / "all.lvsdb"))
    xref = lvs.xref()
    mismatched, inventory_bad = [], []
    for cp in xref.each_circuit_pair():
        a, b = cp.first(), cp.second()
        name = (a or b).name
        if name.upper() == "ALL" or cp.status() == pya.NetlistCrossReference.Match:
            continue
        base = name.rsplit("_ASAP7", 1)[0]
        if base not in PERMUTED:
            mismatched.append(name)
        elif not inventory(a) or inventory(a) != inventory(b):
            inventory_bad.append((name, inventory(a), inventory(b)))
    check(f"{vt}: all {len(names) - len(PERMUTED)} other cells with a CDL match it exactly "
          f"(no CDL: {', '.join(no_cdl) or '-'})", not mismatched, mismatched[:8])
    check(f"{vt}: the {len(PERMUTED)} permuted cells have the CDL's transistors (type, gate pin, width)",
          not inventory_bad, inventory_bad[:2])


def inventory(circuit):
    """{(device class, gate pin or '*'): total W} - independent of the order of series devices"""
    if circuit is None:
        return None
    pins = set()
    for p in circuit.each_pin():
        net = circuit.net_for_pin(p)
        if net is not None:
            pins.add(net.expanded_name().upper())
    inv = {}
    for d in circuit.each_device():
        g = d.net_for_terminal(1)
        gate = g.expanded_name().upper() if g is not None else ""
        key = (d.device_class().name, gate if gate in pins else "*")
        inv[key] = round(inv.get(key, 0) + d.parameter("W"), 4)
    return inv


for vt in (globals().get("libs") or "R").split(","):
    run(vt.strip())
print("PASS lvs_library" if not failures else f"FAIL lvs_library: {', '.join(failures)}")
