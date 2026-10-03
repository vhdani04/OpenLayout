#!/usr/bin/env python3
"""Convert ASAP7 HSPICE BSIM-CMG (level 72) model cards to ngspice OSDI form.

  .model nmos_rvt nmos level = 72   ->   .model nmos_rvt bsimcmg_va type=1
  .model pmos_rvt pmos level = 72   ->   .model pmos_rvt bsimcmg_va type=-1

Devices using these models must be instantiated as OSDI instances
(name starting with N), e.g.:  N1 d g s b nmos_rvt l=21n nfin=3
"""
import re
import sys
from pathlib import Path

MODEL_RE = re.compile(r"^\.model\s+(\S+)\s+(nmos|pmos)\s+level\s*=\s*72\s*$", re.I)
# Parameters present in the 107 cards that the BSIM-CMG Verilog-A does not accept.
DROP_PARAMS = {"version"}


def convert(text: str) -> str:
    out = []
    for line in text.splitlines():
        m = MODEL_RE.match(line.strip())
        if m:
            name, kind = m.groups()
            out.append(f".model {name} bsimcmg_va type={1 if kind.lower() == 'nmos' else -1}")
            continue
        if line.startswith("+") and DROP_PARAMS:
            pairs = re.findall(r"(\w+)\s*=\s*(\S+)", line)
            kept = [f"{k} = {v}" for k, v in pairs if k.lower() not in DROP_PARAMS]
            line = "+" + "   ".join(kept) if kept else "*" + line
        out.append(line)
    return "\n".join(out) + "\n"


def main(src_dir: str, dst_dir: str) -> None:
    dst = Path(dst_dir)
    dst.mkdir(parents=True, exist_ok=True)
    for corner in ("TT", "FF", "SS"):
        src = Path(src_dir) / f"7nm_{corner}_160803.pm"
        (dst / f"7nm_{corner}.pm").write_text(convert(src.read_text()))
        print(f"wrote {dst / f'7nm_{corner}.pm'}")
    lib = ["* ASAP7 corner library (BSIM-CMG via OSDI). Usage:  .lib asap7.lib tt"]
    for corner in ("TT", "FF", "SS"):
        lib += [f".lib {corner.lower()}", f".include 7nm_{corner}.pm", f".endl {corner.lower()}"]
    (dst / "asap7.lib").write_text("\n".join(lib) + "\n")
    print(f"wrote {dst / 'asap7.lib'}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
