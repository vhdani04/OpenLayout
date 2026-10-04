"""OpenLayout_ASAP7 PCell library: FinFETs (nmos/pmos), via stacks and the standard-cell frame.

FinFET geometry follows the ASAP7 7.5-track standard cells (DRM r1p7):
  gates on a 54 nm pitch (20 nm wide) with one dummy gate on each side, fins 7 nm on a 27 nm grid,
  ACTIVE 10 nm past the outer fins, SDT/LISD source-drain contacts (24 nm) between gates, a LIG
  strap tying all gate fingers together, GCUT at both gate ends, and implant/VT layers.
Source/drain columns alternate s, d, s, ... from the left (at x = 54, 108, ...); the gate strap sits
on `gate_side`.

Standard-cell row mode (`row`): the device is drawn in the coordinates of a 270 nm (7.5-track) cell
placed at y = 0, exactly like the library cells - nMOS on fins 1..nfin from the bottom, pMOS on
fins 8..9-nfin from the top, gates running to the middle of the cell (so an nMOS and a pMOS in the
same column form one continuous gate) without a strap, dummy gates cut at mid-height.

Chaining (`abut_left` / `abut_right`): the dummy gate on that side is left out and the diffusion
runs on into the neighbour's, whose outer source/drain column coincides with this one's (devices
overlap by two gate pitches). The shared column keeps its contact unless `contact_left/right` is
off (e.g. the inner node of a series stack).

The standard-cell frame (`stdcell`): boundary, well/implant split, VT layer, the full fin grid,
M1 + LIG rails with GCUT over them, and dummy gates at both cell edges.
"""
import pya

from .asap7 import DBU, LAYERS, NM, VIAS, VT_LAYER

LIBRARY = "OpenLayout_ASAP7"
CPP, FIN_PITCH, CELL_HEIGHT, MID = 54, 27, 270, 135
ROW_MAX_FINS = 3


def mos_geometry(kind: str, nfin: int, nf: int, gate_side: str = "", vt: str = "rvt", row: bool = False,
                 abut_left: bool = False, abut_right: bool = False,
                 contact_left: bool = True, contact_right: bool = True) -> dict:
    """Shapes {layer: [(x1, y1, x2, y2) nm]} and terminals {term: [(x, y, layer)]} of one FinFET."""
    w = CPP * (nf + 2)
    gates = [27 + CPP * i for i in range(nf + 2)]           # gates[0] and gates[-1] are dummies
    real = gates[1:-1]
    dummies = ([] if abut_left else [gates[0]]) + ([] if abut_right else [gates[-1]])
    s = {name: [] for name in ("fin", "active", "gate", "gcut", "lig", "lisd", "sdt")}
    terminals = {"g": [], "s": [], "d": []}

    if row:
        nfin = min(nfin, ROW_MAX_FINS)
        if kind == "nmos":
            fins = range(1, nfin + 1)
            gy = (-5, MID)                                     # gate from below the rail to mid-cell
            half, rail_cut, g_y = (0, 0, w, MID), (0, -22, w, 22), MID - 14
        else:
            fins = range(9 - nfin, 9)
            gy = (MID, CELL_HEIGHT + 5)
            half, rail_cut, g_y = (0, MID, w, CELL_HEIGHT), (0, CELL_HEIGHT - 22, w, CELL_HEIGHT + 22), MID + 14
        act_bot = FIN_PITCH * fins[0]                          # 10 nm below the lowest fin
        act_top = FIN_PITCH * (fins[-1] + 1)                   # 10 nm above the highest fin
        for c in real + dummies:
            s["gate"].append((c - 10, gy[0], c + 10, gy[1]))
        s["gcut"].append(rail_cut)
        s["gcut"] += [(c - 27, MID - 22, c + 27, MID + 22) for c in dummies]   # P/N dummy halves apart
        terminals["g"] = [(c, g_y, "gate") for c in real]
        implant = half
        bbox = (0, min(half[1], rail_cut[1]), w, max(half[3], rail_cut[3]))
    else:
        side = gate_side or ("top" if kind == "nmos" else "bottom")
        fins = range(1, nfin + 1)
        act_bot, act_top = 27, 27 * (nfin + 1)
        if side == "top":
            strap = act_top + 27
            yb, yt = act_bot - 32, strap + 43
        else:
            strap = act_bot - 27
            yb, yt = strap - 43, act_top + 32
        for c in real + dummies:
            s["gate"].append((c - 10, yb, c + 10, yt))
        s["gcut"] += [(0, yb - 17, w, yb + 27), (0, yt - 27, w, yt + 17)]
        # the strap reaches past the outer fingers; on a chained side only to the gate edge, clear of
        # the neighbour's strap
        x1 = real[0] - (10 if abut_left else 27)
        x2 = real[-1] + (10 if abut_right else 12)
        s["lig"].append((x1, strap - 11, x2, strap + 11))
        terminals["g"] = [((x1 + x2) / 2, strap, "lig")]
        implant = (0, yb, w, yt)
        bbox = (0, yb - 17, w, yt + 17)

    for k in fins:
        c = 13.5 + FIN_PITCH * k
        s["fin"].append((0, c - 3.5, w, c + 3.5))
    left = CPP - 12 if abut_left else gates[0] + 19
    right = CPP * (nf + 1) + 12 if abut_right else gates[-1] - 19
    s["active"].append((left, act_bot, right, act_top))
    for j in range(nf + 1):
        x = CPP * (j + 1)
        contact = not ((j == 0 and abut_left and not contact_left) or (j == nf and abut_right and not contact_right))
        if contact:
            s["lisd"].append((x - 12, act_bot, x + 12, act_top))
            s["sdt"].append((x - 12, act_bot, x + 12, act_top))
        terminals["s" if j % 2 == 0 else "d"].append((x, (act_bot + act_top) / 2, "lisd" if contact else "sd"))
    s["nselect" if kind == "nmos" else "pselect"] = [implant]
    if kind == "pmos":
        s["well"] = [implant]
    if VT_LAYER.get(vt):
        s[VT_LAYER[vt]] = [implant]
    return {"shapes": s, "terminals": terminals, "bbox": bbox}


MOS_PARAMS = ("nfin", "nf", "gate_side", "vt", "row", "abut_left", "abut_right", "contact_left", "contact_right")


def mos_geometry_from(kind: str, params: dict) -> dict:
    """mos_geometry for a PCell parameter dict (missing ones take the defaults)."""
    kw = {k: params[k] for k in MOS_PARAMS if params.get(k) is not None}
    kw["nfin"], kw["nf"] = int(kw.get("nfin", 1)), int(kw.get("nf", 1))
    for k in ("row", "abut_left", "abut_right", "contact_left", "contact_right"):
        if k in kw:
            kw[k] = bool(kw[k])
    return mos_geometry(kind, **kw)


def stdcell_geometry(cpp: int, vt: str = "rvt") -> dict:
    """The standard-cell frame: cpp gate pitches wide, 270 nm (7.5 tracks) high, origin bottom-left."""
    w = CPP * cpp
    s = {
        "boundary": [(0, 0, w, CELL_HEIGHT)],
        "nselect": [(0, 0, w, MID)],
        "pselect": [(0, MID, w, CELL_HEIGHT)],
        "well": [(0, MID, w, CELL_HEIGHT)],
        "fin": [(0, 13.5 + FIN_PITCH * k - 3.5, w, 13.5 + FIN_PITCH * k + 3.5) for k in range(10)],
        "m1": [(0, -9, w, 9), (0, CELL_HEIGHT - 9, w, CELL_HEIGHT + 9)],
        "lig": [(0, -8, w, 8), (0, CELL_HEIGHT - 8, w, CELL_HEIGHT + 8)],
        "gcut": [(0, -22, w, 22), (0, CELL_HEIGHT - 22, w, CELL_HEIGHT + 22)],
        "gate": [],
    }
    if cpp >= 2:   # dummy gates on both cell edges, cut at mid-height like the library cells
        for c in (27, w - 27):
            s["gate"].append((c - 10, -5, c + 10, CELL_HEIGHT + 5))
            s["gcut"].append((c - 27, MID - 22, c + 27, MID + 22))
    if VT_LAYER.get(vt):
        s[VT_LAYER[vt]] = [(0, 0, w, CELL_HEIGHT)]
    return {"shapes": s, "rails": {"VSS": (0, 0), "VDD": (0, CELL_HEIGHT)}}


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
        self.param("row", self.TypeBoolean, "Standard-cell row (place at cell y = 0)", default=False)
        self.param("abut_left", self.TypeBoolean, "Chained on the left (shared diffusion)", default=False)
        self.param("abut_right", self.TypeBoolean, "Chained on the right (shared diffusion)", default=False)
        self.param("contact_left", self.TypeBoolean, "Contact on the shared left diffusion", default=True)
        self.param("contact_right", self.TypeBoolean, "Contact on the shared right diffusion", default=True)

    def display_text_impl(self):
        return f"{self.kind}_{self.vt} nfin={self.nfin} nf={self.nf}"

    def coerce_parameters_impl(self):
        self.nfin = max(1, min(int(self.nfin), ROW_MAX_FINS if self.row else 40))
        self.nf = max(1, min(int(self.nf), 64))
        self.l = 0.020

    def produce_impl(self):
        draw(self.cell, mos_geometry(self.kind, self.nfin, self.nf, self.gate_side, self.vt, self.row,
                                     self.abut_left, self.abut_right, self.contact_left, self.contact_right)["shapes"])


class StdCellFrame(pya.PCellDeclarationHelper):
    """Standard-cell frame (template): place at the origin of a custom standard cell."""

    def __init__(self):
        super().__init__()
        self.param("cpp", self.TypeInt, "Width (gate pitches of 54 nm)", default=3)
        self.param("vt", self.TypeString, "Threshold voltage", default="rvt",
                   choices=[["RVT", "rvt"], ["LVT", "lvt"], ["SLVT", "slvt"]])

    def display_text_impl(self):
        return f"stdcell frame {self.cpp} CPP ({CPP * self.cpp} nm) {self.vt}"

    def coerce_parameters_impl(self):
        self.cpp = max(1, min(int(self.cpp), 400))

    def produce_impl(self):
        draw(self.cell, stdcell_geometry(self.cpp, self.vt)["shapes"])


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
        self.description = "OpenLayout ASAP7 devices: FinFET PCells, via stacks, standard-cell frame"
        self.layout().dbu = DBU
        self.layout().register_pcell("nmos", FinFET("nmos"))
        self.layout().register_pcell("pmos", FinFET("pmos"))
        self.layout().register_pcell("via", Via())
        self.layout().register_pcell("stdcell", StdCellFrame())
        self.technology = "asap7"
        self.register(LIBRARY)


_library = None


def register_library() -> pya.Library:
    """Register the PCell library once per process (GUI autorun and batch scripts)."""
    global _library
    if _library is None:
        _library = ASAP7Library()
    return _library
