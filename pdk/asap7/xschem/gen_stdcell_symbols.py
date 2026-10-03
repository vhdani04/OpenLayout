#!/usr/bin/env python3
"""Generate xschem symbol libraries for the ASAP7 7.5T standard cells, one library per VT flavor:
  <out>/asap7sc7p5t_28_<flavor>/<cell>/<cell>.sym

Pin order follows the CDL subcircuit (so @pinlist matches the ngspice subckt); pin directions
come from the Verilog models. Usage: gen_stdcell_symbols.py <asap7sc7p5t_28 dir> <output dir>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stdcells import FLAVORS, POWER, cdl_path, read_cdl, read_directions  # noqa: E402

HEADER = "v {xschem version=3.4.8RC file_version=1.3}\nG {}\n"
PITCH, HALF_W, STUB = 20, 50, 20


def symbol(cell: str, ports: list, dirs: dict, flavor: str) -> str:
    ins = [p for p in ports if dirs.get(p) == "in"]
    outs = [p for p in ports if dirs.get(p) == "out" or (p not in dirs and p not in POWER)]
    half_h = max(len(ins), len(outs), 1) * PITCH // 2 + 10
    pos = {}
    for side, pins, x in ((ins, ins, -HALF_W - STUB), (outs, outs, HALF_W + STUB)):
        y0 = -(len(pins) - 1) * PITCH // 2
        for i, p in enumerate(pins):
            pos[p] = (x, y0 + i * PITCH)
    pos["VDD"], pos["VSS"] = (0, -half_h - STUB), (0, half_h + STUB)

    body = [f"P 4 5 {-HALF_W} {-half_h} {HALF_W} {-half_h} {HALF_W} {half_h} {-HALF_W} {half_h} "
            f"{-HALF_W} {-half_h} {{}}"]
    for p in ports:  # pin boxes in CDL order -> @pinlist order
        x, y = pos[p]
        d = "inout" if p in POWER else dirs.get(p, "out")
        body.append(f"B 5 {x - 2.5} {y - 2.5} {x + 2.5} {y + 2.5} {{name={p} dir={d}}}")
        if p in POWER:
            edge = -half_h if p == "VDD" else half_h
            body.append(f"L 4 0 {y} 0 {edge} {{}}")
            body.append(f"T {{{p}}} 5 {edge + (-12 if p == 'VDD' else 2)} 0 0 0.12 0.12 {{}}")
        else:
            edge = -HALF_W if x < 0 else HALF_W
            body.append(f"L 4 {x} {y} {edge} {y} {{}}")
            tx = edge + 4 if x < 0 else edge - 4
            body.append(f"T {{{p}}} {tx} {y - 6} 0 {0 if x < 0 else 1} 0.15 0.15 {{}}")
    label = cell.replace("_ASAP7_75t_" + flavor, "")
    return HEADER + f"""K {{type=subcircuit
format="X@name @pinlist @symname"
template="name=U1"
spice_primitive=true
}}
V {{}}
S {{}}
E {{}}
""" + "\n".join(body) + f"""
T {{{label}}} 0 {-half_h - 2} 0 0 0.2 0.2 {{hcenter=true layer=8}}
T {{@name}} {HALF_W + 4} {-half_h - 14} 0 0 0.15 0.15 {{}}
"""


def main(stdcells: str, out_dir: str) -> None:
    for flavor in FLAVORS:
        lib = Path(out_dir) / f"asap7sc7p5t_28_{flavor}"
        cells = read_cdl(cdl_path(Path(stdcells), flavor))
        dirs = read_directions(Path(stdcells), flavor)
        for cell, (ports, _) in cells.items():
            d = lib / cell
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{cell}.sym").write_text(symbol(cell, ports, dirs.get(cell, {}), flavor))
        meta = {"readonly": True,
                "description": f"ASAP7 7.5-track standard cells ({FLAVORS[flavor]})",
                "layout_gds": f"$OPENLAYOUT_HOME/pdk/asap7/klayout/tech/asap7/libraries/{lib.name}.gds"}
        (lib / "openlayout.lib.json").write_text(json.dumps(meta, indent=1) + "\n")
        missing = [c for c in cells if c not in dirs]
        print(f"wrote {lib} ({len(cells)} cells, {len(missing)} without Verilog directions)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
