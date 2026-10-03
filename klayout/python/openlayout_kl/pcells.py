"""OpenLayout_ASAP7 PCell library: FinFETs (nmos/pmos) and via stacks.

FinFET geometry follows the ASAP7 7.5-track standard cells (DRM r1p7):
  gates on a 54 nm pitch (20 nm wide) with one dummy gate on each side, fins 7 nm on a 27 nm grid,
  ACTIVE 10 nm past the outer fins, SDT/LISD source-drain contacts (24 nm) between gates, a LIG
  strap tying all gate fingers together, GCUT at both gate ends, and implant/VT layers.
Source/drain columns alternate s, d, s, ... from the left; the gate strap sits on `gate_side`.
"""
import pya

from .asap7 import DBU, LAYERS, NM, VIAS, VT_LAYER

LIBRARY = "OpenLayout_ASAP7"


def mos_geometry(kind: str, nfin: int, nf: int, gate_side: str = "", vt: str = "rvt") -> dict:
    """Shapes {layer: [(x1, y1, x2, y2) nm]} and terminals {term: [(x, y, layer)]} of one FinFET."""
    side = gate_side or ("top" if kind == "nmos" else "bottom")
    w = 54 * (nf + 2)
    gates = [27 + 54 * i for i in range(nf + 2)]           # gates[0] and gates[-1] are dummies
    act_bot, act_top = 27, 27 * (nfin + 1)
    if side == "top":
        strap = act_top + 27
        yb, yt = act_bot - 32, strap + 43
    else:
        strap = act_bot - 27
        yb, yt = strap - 43, act_top + 32
    s = {name: [] for name in ("fin", "active", "gate", "gcut", "lig", "lisd", "sdt")}
    for k in range(1, nfin + 1):
        c = 13.5 + 27 * k
        s["fin"].append((0, c - 3.5, w, c + 3.5))
    s["active"].append((gates[0] + 19, act_bot, gates[-1] - 19, act_top))
    for c in gates:
        s["gate"].append((c - 10, yb, c + 10, yt))
    s["gcut"] += [(0, yb - 17, w, yb + 27), (0, yt - 27, w, yt + 17)]
    s["lig"].append((gates[1] - 27, strap - 11, gates[nf] + 12, strap + 11))
    terminals = {"g": [((gates[1] - 27 + gates[nf] + 12) / 2, strap, "lig")], "s": [], "d": []}
    for j in range(nf + 1):
        x = 54 * (j + 1)
        s["lisd"].append((x - 12, act_bot, x + 12, act_top))
        s["sdt"].append((x - 12, act_bot, x + 12, act_top))
        terminals["s" if j % 2 == 0 else "d"].append((x, (act_bot + act_top) / 2, "lisd"))
    implant = (0, yb, w, yt)
    s["nselect" if kind == "nmos" else "pselect"] = [implant]
    if kind == "pmos":
        s["well"] = [implant]
    if VT_LAYER.get(vt):
        s[VT_LAYER[vt]] = [implant]
    return {"shapes": s, "terminals": terminals, "bbox": (0, yb - 17, w, yt + 17)}


def via_geometry(bottom: str, top: str, rows: int = 1, cols: int = 1) -> dict:
    """Via array between two adjacent conductors, with enclosing pads on both."""
    via, size = VIAS[(bottom, top)]
    pitch = size + 30
    vias = [(c * pitch, r * pitch, c * pitch + size, r * pitch + size) for r in range(rows) for c in range(cols)]
    x2, y2 = (cols - 1) * pitch + size, (rows - 1) * pitch + size
    enc = {"lisd": (3, 5), "lig": (2, 2), "m1": (2, 5)}
    ex, ey = enc.get(bottom, (2, 5))
    tx, ty = enc.get(top, (5, 2))
    return {"shapes": {via: vias, bottom: [(-ex, -ey, x2 + ex, y2 + ey)], top: [(-tx, -ty, x2 + tx, y2 + ty)]},
            "terminals": {"t": [(x2 / 2, y2 / 2, top)]}}


def nm_box(b) -> pya.Box:
    return pya.Box(round(b[0] * NM), round(b[1] * NM), round(b[2] * NM), round(b[3] * NM))


def draw(cell: pya.Cell, shapes: dict) -> None:
    layout = cell.layout()
    for name, boxes in shapes.items():
        li = layout.layer(LAYERS[name], 0)
        for b in boxes:
            cell.shapes(li).insert(nm_box(b))


class FinFET(pya.PCellDeclarationHelper):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.param("vt", self.TypeString, "Threshold voltage", default="rvt",
                   choices=[["RVT", "rvt"], ["LVT", "lvt"], ["SLVT", "slvt"], ["SRAM", "sram"]])
        self.param("nfin", self.TypeInt, "Fins per finger", default=2)
        self.param("nf", self.TypeInt, "Fingers", default=1)
        self.param("l", self.TypeDouble, "Gate length (um)", default=0.020, readonly=True)
        self.param("gate_side", self.TypeString, "Gate contact side",
                   default="top" if kind == "nmos" else "bottom", choices=[["Top", "top"], ["Bottom", "bottom"]])

    def display_text_impl(self):
        return f"{self.kind}_{self.vt} nfin={self.nfin} nf={self.nf}"

    def coerce_parameters_impl(self):
        self.nfin = max(1, min(int(self.nfin), 40))
        self.nf = max(1, min(int(self.nf), 64))
        self.l = 0.020

    def produce_impl(self):
        draw(self.cell, mos_geometry(self.kind, self.nfin, self.nf, self.gate_side, self.vt)["shapes"])


class Via(pya.PCellDeclarationHelper):
    PAIRS = [f"{b}-{t}" for b, t in VIAS]

    def __init__(self):
        super().__init__()
        self.param("layers", self.TypeString, "Layers", default="lisd-m1",
                   choices=[[p.upper().replace("-", " → "), p] for p in self.PAIRS])
        self.param("rows", self.TypeInt, "Rows", default=1)
        self.param("cols", self.TypeInt, "Columns", default=1)

    def display_text_impl(self):
        return f"via {self.layers} {self.rows}x{self.cols}"

    def coerce_parameters_impl(self):
        self.rows = max(1, min(int(self.rows), 32))
        self.cols = max(1, min(int(self.cols), 32))
        if self.layers not in self.PAIRS:
            self.layers = "lisd-m1"

    def produce_impl(self):
        bottom, top = self.layers.split("-")
        draw(self.cell, via_geometry(bottom, top, self.rows, self.cols)["shapes"])


class ASAP7Library(pya.Library):
    def __init__(self):
        super().__init__()
        self.description = "OpenLayout ASAP7 devices: FinFET PCells and via stacks"
        self.layout().dbu = DBU
        self.layout().register_pcell("nmos", FinFET("nmos"))
        self.layout().register_pcell("pmos", FinFET("pmos"))
        self.layout().register_pcell("via", Via())
        self.technology = "asap7"
        self.register(LIBRARY)


_library = None


def register_library() -> pya.Library:
    """Register the PCell library once per process (GUI autorun and batch scripts)."""
    global _library
    if _library is None:
        _library = ASAP7Library()
    return _library
