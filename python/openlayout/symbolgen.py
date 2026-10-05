"""Generate an xschem symbol from a schematic's pins, like creating a cellview from a cellview.

Inputs go on the left, outputs on the right, supply pins (VDD/VSS/...) on top/bottom and other
input-outputs on the right below the outputs, each on a stub with its name inside the body. The
body is a green rectangle with @name above and @symname below it, and a red selection box (outline
only) encloses the body and pins, with the pins on its edges. The box is hide=instance: it
is not drawn where the symbol is placed, it only sets the instance's hover/selection area.
Pins keep the schematic's top-to-bottom order.

  openlayout make-symbol <cell.sch> [--force]
"""
import argparse
import re
import sys
from pathlib import Path

HEADER = "v {xschem version=3.4.8RC file_version=1.3}\nG {}\n"
PIN_SYMBOLS = {"ipin.sym": "in", "opin.sym": "out", "iopin.sym": "inout"}
SUPPLY_TOP = re.compile(r"^(vdd|vcc|vpwr|vpp|avdd|dvdd|vddio)\w*$", re.I)
SUPPLY_BOTTOM = re.compile(r"^(vss|gnd|vgnd|vnb|avss|dvss|vssio|0)\w*$", re.I)
PITCH, STUB, CHAR = 20, 20, 6          # xschem units; CHAR ~ width of one label character
LABEL, SMALL = 0.2, 0.15               # text sizes


def schematic_pins(sch: Path) -> list:
    """[(name, direction, y)] of the ipin/opin/iopin instances in a schematic."""
    pins = []
    for line in sch.read_text().splitlines():
        m = re.match(r"^C \{([^}]*)\} (\S+) (\S+) \S+ \S+ \{(.*)\}\s*$", line)
        if not m or Path(m.group(1)).name not in PIN_SYMBOLS:
            continue
        lab = re.search(r'(?:^|\s)lab=("(?:[^"\\]|\\.)*"|\S+)', m.group(4))
        if lab:
            pins.append((lab.group(1).strip('"'), PIN_SYMBOLS[Path(m.group(1)).name], float(m.group(3))))
    return pins


def _snap(v: float, g: int = 10) -> int:
    return int(round(v / g) * g)


def symbol_text(pins: list) -> str:
    ordered = sorted(pins, key=lambda p: p[2])
    left = [p for p in ordered if p[1] == "in"]
    top = [p for p in ordered if p[1] == "inout" and SUPPLY_TOP.match(p[0])]
    bottom = [p for p in ordered if p[1] == "inout" and SUPPLY_BOTTOM.match(p[0]) and p not in top]
    right = [p for p in ordered if p[1] == "out"] + \
            [p for p in ordered if p[1] == "inout" and p not in top and p not in bottom]

    rows = max(len(left), len(right), 1)
    height = _snap(rows * PITCH + 20, 20)
    maxl = max((len(p[0]) for p in left), default=0)
    maxr = max((len(p[0]) for p in right), default=0)
    width = max(80, (maxl + maxr) * CHAR + 40, len(top) * PITCH + 20, len(bottom) * PITCH + 20)
    width = _snap(width + 10, 20)
    x1, y1 = -width // 2, -height // 2
    x2, y2 = x1 + width, y1 + height

    lines, rects, texts = [], [], []
    lines += [f"L 4 {x1} {y1} {x2} {y1} {{}}", f"L 4 {x2} {y1} {x2} {y2} {{}}",
              f"L 4 {x2} {y2} {x1} {y2} {{}}", f"L 4 {x1} {y2} {x1} {y1} {{}}"]

    def column(pins_):
        n = len(pins_)
        y0 = _snap((y1 + y2) / 2 - (n - 1) * PITCH / 2)
        return [(p, y0 + i * PITCH) for i, p in enumerate(pins_)]

    def row(pins_):
        n = len(pins_)
        x0 = _snap((x1 + x2) / 2 - (n - 1) * PITCH / 2)
        return [(p, x0 + i * PITCH) for i, p in enumerate(pins_)]

    def pin_box(name, d, x, y):
        rects.append(f"B 5 {x - 2.5} {y - 2.5} {x + 2.5} {y + 2.5} {{name={name} dir={d}}}")

    for (name, d, _), y in column(left):
        lines.append(f"L 4 {x1 - STUB} {y} {x1} {y} {{}}")
        pin_box(name, d, x1 - STUB, y)
        texts.append(f"T {{{name}}} {x1 + 4} {y - 6} 0 0 {LABEL} {LABEL} {{}}")
    for (name, d, _), y in column(right):
        lines.append(f"L 4 {x2} {y} {x2 + STUB} {y} {{}}")
        pin_box(name, d, x2 + STUB, y)
        texts.append(f"T {{{name}}} {x2 - 4} {y - 6} 0 1 {LABEL} {LABEL} {{}}")
    for (name, d, _), x in row(top):
        lines.append(f"L 4 {x} {y1 - STUB} {x} {y1} {{}}")
        pin_box(name, d, x, y1 - STUB)
        texts.append(f"T {{{name}}} {x} {y1 + 3} 0 0 {SMALL} {SMALL} {{hcenter=true}}")
    for (name, d, _), x in row(bottom):
        lines.append(f"L 4 {x} {y2} {x} {y2 + STUB} {{}}")
        pin_box(name, d, x, y2 + STUB)
        texts.append(f"T {{{name}}} {x} {y2 - 13} 0 0 {SMALL} {SMALL} {{hcenter=true}}")

    name_y = y1 - (STUB if top else 0) - 22
    cell_y = y2 + (STUB if bottom else 0) + 6
    texts.append(f"T {{@name}} {x1} {name_y} 0 0 {LABEL} {LABEL} {{}}")
    texts.append(f"T {{@symname}} {x1} {cell_y} 0 0 {LABEL} {LABEL} {{}}")

    # red selection box (outline only): the body plus the pin stubs, with the pins on
    # its edges; labels stay outside. Not drawn in instances (hide=instance, OpenLayout xschem patch). On the 10 grid, so its edges can be dragged on the grid.
    bx1 = x1 - (STUB if left else 0)
    bx2 = x2 + (STUB if right else 0)
    by1 = y1 - (STUB if top else 0)
    by2 = y2 + (STUB if bottom else 0)
    selection = f"B 7 {bx1} {by1} {bx2} {by2} {{fill=false hide=instance}}"

    k = 'K {type=subcircuit\nformat="@name @pinlist @symname"\ntemplate="name=x1"\n}\n'
    return HEADER + k + "V {}\nS {}\nE {}\n" + "\n".join([selection] + lines + rects + texts) + "\n"


BLANK = HEADER + ('K {type=subcircuit\nformat="@name @pinlist @symname"\ntemplate="name=x1"\n}\n'
                  "V {}\nS {}\nE {}\nB 7 -80 -50 80 50 {fill=false hide=instance}\n")


def make_symbol(sch: Path, force: bool = False) -> Path:
    sch = Path(sch)
    sym = sch.with_suffix(".sym")
    if sym.exists() and not force:
        raise FileExistsError(f"{sym} exists (use --force to replace it)")
    pins = schematic_pins(sch)
    if not pins:
        raise ValueError(f"{sch.name} has no pins (ipin/opin/iopin)")
    sym.write_text(symbol_text(pins))
    return sym


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openlayout make-symbol", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("schematic")
    ap.add_argument("--force", action="store_true", help="replace an existing symbol")
    a = ap.parse_args(argv)
    try:
        sym = make_symbol(Path(a.schematic), a.force)
    except (FileExistsError, ValueError, OSError) as e:
        print(e)
        return 1
    print(sym)
    return 0


if __name__ == "__main__":
    sys.exit(main())
