"""Shared parsing of the ASAP7 7.5-track standard-cell views (CDL netlists + Verilog models)."""
import re
from pathlib import Path

FLAVORS = {"R": "RVT", "L": "LVT", "SL": "SLVT", "SRAM": "SRAM"}  # cell suffix -> Verilog tag
POWER = ("VDD", "VSS")


def cdl_path(stdcells: Path, flavor: str) -> Path:
    return stdcells / "CDL" / "LVS" / f"asap7sc7p5t_28_{flavor}.cdl"


def read_cdl(path: Path) -> dict:
    """Return {cell: (ports, [device lines])} from a CDL file."""
    cells, cur = {}, None
    for line in path.read_text().splitlines():
        f = line.split()
        if not f or line.startswith("*"):
            continue
        if f[0].upper() == ".SUBCKT":
            cur = f[1]
            cells[cur] = (f[2:], [])
        elif f[0].upper() == ".ENDS":
            cur = None
        elif cur:
            cells[cur][1].append(line)
    return cells


def read_directions(stdcells: Path, flavor: str) -> dict:
    """Return {cell: {pin: 'in'|'out'}} from the Verilog models."""
    dirs = {}
    for v in sorted((stdcells / "Verilog").glob(f"*_{FLAVORS[flavor]}_*.v")):
        cell = None
        for line in v.read_text().splitlines():
            m = re.match(r"\s*module\s+(\w+)", line)
            if m:
                cell = m.group(1)
                dirs[cell] = {}
                continue
            m = re.match(r"\s*(input|output)\s+(.+);", line)
            if cell and m:
                for pin in m.group(2).split(","):
                    dirs[cell][pin.strip()] = "in" if m.group(1) == "input" else "out"
            if line.strip().startswith("endmodule"):
                cell = None
    return dirs
