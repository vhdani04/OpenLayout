#!/usr/bin/env python3
"""Generate the xschem symbol library `asap7_devices` (cells: <lib>/<cell>/<cell>.sym).

Transistors netlist as OSDI BSIM-CMG instances: the schematic name M1 becomes "NM1" in the
SPICE netlist (OSDI devices must start with N). The asap7_corner cell emits `.lib asap7.lib <corner>`.
"""
from pathlib import Path

LIB = Path(__file__).resolve().parent / "asap7_devices"
FLAVORS = ["rvt", "lvt", "slvt", "sram"]
HEADER = "v {xschem version=3.4.8RC file_version=1.3}\nG {}\n"


def mos_symbol(kind: str, flavor: str) -> str:
    model = f"{kind}_{flavor}"
    nmos = kind == "nmos"
    # Drain on top for NMOS, source on top for PMOS (conventional orientation).
    top, bot = ("d", "s") if nmos else ("s", "d")
    y = {top: -30, "g": 0, bot: 30, "b": 0}
    x = {"d": 20, "g": -20, "s": 20, "b": 20}
    # Pin boxes must be listed d, g, s, b: xschem's @pinlist follows this order (BSIM-CMG: d g s e).
    pins = "".join(
        f"B 5 {x[p] - 2.5} {y[p] - 2.5} {x[p] + 2.5} {y[p] + 2.5} "
        f"{{name={p} dir={'in' if p in 'gb' else 'inout'}}}\n"
        for p in "dgsb")
    bubble = "" if nmos else "A 4 -8.75 0 3.75 180 360 {}\n"
    gate_end = -5 if nmos else -12.5
    arrow = ("L 4 10 20 15 17.5 {}\nL 4 10 20 15 22.5 {}\n" if nmos
             else "L 4 10 -20 15 -17.5 {}\nL 4 10 -20 15 -22.5 {}\n")
    return HEADER + f"""K {{type={kind}
format="N@name @pinlist {model} l=@l nfin=@nfin nf=@nf m=@m"
template="name=M1 l=20n nfin=2 nf=1 m=1"
}}
V {{}}
S {{}}
E {{}}
L 4 5 -30 5 30 {{}}
L 4 5 -20 20 -20 {{}}
L 4 20 -30 20 -20 {{}}
L 4 5 20 20 20 {{}}
L 4 20 20 20 30 {{}}
L 4 -5 -15 -5 15 {{}}
L 4 -20 0 {gate_end} 0 {{}}
L 4 5 0 20 0 {{}}
{bubble}{arrow}{pins}T {{@name}} 25 -15 0 0 0.2 0.2 {{}}
T {{{model}}} 25 5 0 0 0.15 0.15 {{layer=8}}
T {{nfin=@nfin nf=@nf}} 25 15 0 0 0.15 0.15 {{}}
T {{{top.upper()}}} 7.5 -35 0 0 0.1 0.1 {{}}
T {{{bot.upper()}}} 7.5 27.5 0 0 0.1 0.1 {{}}
"""


CORNER = HEADER + """K {type=netlist_commands
template="name=CORNER1 corner=tt only_toplevel=true"
format=".lib asap7.lib @corner"
}
V {}
S {}
E {}
P 4 5 -20 -20 140 -20 140 20 -20 20 -20 -20 {}
T {ASAP7 models} -10 -15 0 0 0.25 0.25 {}
T {corner: @corner} -10 2.5 0 0 0.25 0.25 {layer=8}
"""


def write(cell: str, text: str) -> None:
    d = LIB / cell
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cell}.sym").write_text(text)


for kind in ("nmos", "pmos"):
    for flavor in FLAVORS:
        write(f"{kind}_{flavor}", mos_symbol(kind, flavor))
write("asap7_corner", CORNER)
print(f"wrote {len(list(LIB.glob('*/*.sym')))} symbols to {LIB}")
