"""A testbench for a cell, ready for OLSim: tb_<cell> with the cell's symbol, the supply source
(VDD = {vdd}), a label on every pin for the vector file to drive or check, a load on every output
({cload}), its OLSim setup (tb_<cell>.olsim) and a starting vector file (tb_<cell>.vec).

    make_testbench(workarea, library, cell) -> tb Cell
"""
from __future__ import annotations

import re
from pathlib import Path

from ..workarea import Cell, Library, Workarea, WorkareaError, check_name
from .setup import Analysis, Output, Setup, Test

HEADER = "v {xschem version=3.4.8RC file_version=1.3}\nG {}\nK {}\nV {}\nS {}\nE {}\n"
PIN_RE = re.compile(r"^B 5 (\S+) (\S+) (\S+) (\S+) \{([^}]*)\}", re.M)
PERIOD_PS = 100


def symbol_pins(sym: Path) -> list[tuple[str, str, float, float]]:
    """[(name, dir, x, y)] of a symbol's pins (the centre of each pin box)."""
    pins = []
    for m in PIN_RE.finditer(sym.read_text()):
        attrs = dict(re.findall(r"(\w+)=(\S+)", m.group(5)))
        if "name" in attrs:
            x = (float(m.group(1)) + float(m.group(3))) / 2
            y = (float(m.group(2)) + float(m.group(4))) / 2
            pins.append((attrs["name"], attrs.get("dir", "inout"), x, y))
    return pins


def is_testbench(cell: Cell) -> bool:
    """A schematic without pins is a testbench; one with pins is a circuit to test."""
    sch = cell.view("schematic")
    if sch is None:
        return False
    return not re.search(r"\{(ipin|opin|iopin)\.sym\}", sch.path.read_text())


def gray(n):
    return [i ^ (i >> 1) for i in range(2 ** n)]


def vector_file(inputs, outputs):
    """(text, number of vectors): every input combination once (Gray code: one input changes per
    vector), then back to the start; outputs X (fill in the expected values to have them checked)."""
    n = min(len(inputs), 6)
    seq = gray(n) + [0] if n else [0, 0]
    while len(seq) < 8:
        seq += seq[1:]
    names = [p for p in inputs[:n]] + list(outputs)
    lines = [f"; stimulus for {', '.join(inputs) or 'the cell'}: every input combination, one input changing per",
             "; vector. Outputs are X (not checked) - write the expected 0 / 1 in their columns to check them.",
             f"radix  {' '.join('1' for _ in names)}",
             f"io     {' '.join(['i'] * n + ['o'] * len(outputs))}",
             f"vname  {' '.join(names)}",
             "tunit  ps",
             f"period {PERIOD_PS}",
             "trise  10",
             "tfall  10",
             "vih    vdd          ; the vdd design variable",
             f"; {' '.join(names)}"]
    for v in seq:
        bits = [str((v >> (n - 1 - i)) & 1) for i in range(n)]
        lines.append("  " + " ".join(bits + ["X"] * len(outputs)))
    return "\n".join(lines) + "\n", len(seq)


def make_testbench(wa: Workarea, lib: Library, cell_name: str, tb_name: str | None = None) -> Cell:
    from ..symbolgen import make_symbol
    if lib.readonly:
        raise WorkareaError(f"library {lib.name} is read-only")
    cell = lib.cell(cell_name)
    if cell is None:
        raise WorkareaError(f"no cell {lib.name}/{cell_name}")
    sym = cell.view("symbol")
    if sym is None:
        if cell.view("schematic") is None:
            raise WorkareaError(f"{cell.key} has neither a symbol nor a schematic")
        make_symbol(cell.view("schematic").path)
        sym = cell.view("symbol")
    tb_name = tb_name or f"tb_{cell_name}"
    check_name("cell", tb_name)
    tb_dir = lib.path / tb_name
    if (tb_dir / f"{tb_name}.sch").exists():
        raise WorkareaError(f"{lib.name}/{tb_name} exists")
    pins = symbol_pins(sym.path)
    supplies = {p for p, *_ in pins if p.upper() in ("VDD", "VSS", "GND", "VCC")}
    inputs = [p for p, d, *_ in pins if d == "in" and p not in supplies]
    outputs = [p for p, d, *_ in pins if d in ("out", "inout") and p not in supplies]

    lines = [HEADER.rstrip(),
             f"T {{Testbench of {lib.name}/{cell_name} - OLSim sets the analyses and the corner}} -380 -230 0 0 0.3 0.3 {{}}",
             f"C {{{lib.name}/{cell_name}/{cell_name}.sym}} 0 0 0 0 {{name=X1}}",
             # the supply: VDD = {vdd} (the cell's vdd / gnd labels are global nets)
             r"C {vsource.sym} -320 0 0 0 {name=VDD value=\{vdd\}}",
             "C {vdd.sym} -320 -30 0 0 {name=l_vdd lab=VDD}",
             "C {gnd.sym} -320 30 0 0 {name=l_vss lab=VSS}"]
    k = 0
    for name, d, x, y in pins:
        k += 1
        left = x < 0
        if name in supplies:
            lab = "VDD" if name.upper() in ("VDD", "VCC") else "VSS"
            lines.append(f"C {{lab_pin.sym}} {x:g} {y:g} 0 {1 if left else 0} {{name=l{k} lab={lab}}}")
            continue
        lines.append(f"C {{lab_pin.sym}} {x:g} {y:g} 0 {1 if left else 0} {{name=l{k} lab={name}}}")
        if name in outputs:                          # a load on the output
            cx = x + (-80 if left else 80)
            lines.append(f"C {{capa.sym}} {cx:g} {y + 30:g} 0 0 {{name=C{k} m=1 value=\\{{cload\\}}}}")
            lines.append(f"C {{lab_pin.sym}} {cx:g} {y:g} 0 0 {{name=lc{k} lab={name}}}")
            lines.append(f"C {{gnd.sym}} {cx:g} {y + 60:g} 0 0 {{name=lg{k} lab=VSS}}")
    tb_dir.mkdir(parents=True, exist_ok=True)
    (tb_dir / f"{tb_name}.sch").write_text("\n".join(lines) + "\n")

    vec, n_vectors = vector_file(inputs, outputs)
    (tb_dir / f"{tb_name}.vec").write_text(vec)
    outs = [Output("tran", p, f'v("{p}")', "", True) for p in inputs + outputs]
    if len(inputs) == 1 and len(outputs) == 1:      # an inverting / buffering stage: its delays
        a, z = inputs[0], outputs[0]
        outs += [Output("tran", "t_out_fall", f'propDelay(v("{a}"), v("{z}"), vdd/2, vdd/2, "fall")'),
                 Output("tran", "t_out_rise", f'propDelay(v("{a}"), v("{z}"), vdd/2, vdd/2, "rise")')]
    stop = f"{n_vectors * PERIOD_PS}p"
    s = Setup(tests=[Test("tran", {"lib": lib.name, "cell": tb_name},
                          [Analysis("tran", True, {"step": "1p", "stop": stop, "start": "0"})], [f"{tb_name}.vec"])],
              variables={"vdd": "0.7", "cload": "1f"}, outputs=outs)
    s.save(tb_dir / f"{tb_name}.olsim")
    wa.reload()
    return lib.cell(tb_name)
