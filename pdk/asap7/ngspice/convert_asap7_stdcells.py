#!/usr/bin/env python3
"""Convert ASAP7 standard-cell CDL (LVS netlists) to ngspice subcircuits using OSDI BSIM-CMG devices.

  MM0 Y A VSS VSS nmos_rvt w=81.0n l=20n nfin=3   ->   NMM0 Y A VSS VSS nmos_rvt l=20n nfin=3

Usage: convert_asap7_stdcells.py <asap7sc7p5t_28 dir> <output dir>
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stdcells import FLAVORS, cdl_path, read_cdl  # noqa: E402


def device_line(line: str) -> str:
    if line[0] in "Mm":
        line = "N" + line
    return re.sub(r"\s+w=\S+", "", line)


def main(stdcells: str, out_dir: str) -> None:
    out = Path(out_dir) / "stdcells"
    out.mkdir(parents=True, exist_ok=True)
    for flavor in FLAVORS:
        cells = read_cdl(cdl_path(Path(stdcells), flavor))
        lines = [f"* ASAP7 7.5T standard cells ({flavor}), converted for ngspice OSDI BSIM-CMG"]
        for cell, (ports, devices) in cells.items():
            lines += [f".subckt {cell} {' '.join(ports)}", *map(device_line, devices), ".ends"]
        dst = out / f"asap7sc7p5t_28_{flavor}.sp"
        dst.write_text("\n".join(lines) + "\n")
        print(f"wrote {dst} ({len(cells)} cells)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
