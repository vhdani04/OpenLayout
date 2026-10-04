"""OpenLayout_ASAP7 PCell library: FinFETs (nmos/pmos), via stacks and the standard-cell frame.

FinFET geometry follows the ASAP7 7.5-track standard cells (DRM r1p7):
  gates on a 54 nm pitch (20 nm wide) with one dummy gate on each side, fins 7 nm on a 27 nm grid,
  ACTIVE 10 nm past the outer fins, SDT/LISD source-drain contacts (24 nm) between gates, and
  implant/VT layers.
  No gate contact: the gates are left open, so a contact (LIG, and a V0 to M1) goes wherever the
  routing wants it - draw it, or place a LIG-M1 via. No GCUT either: where gates are cut depends
  on the cell around the transistor (the standard-cell frame cuts at the rails and its edge
  dummies; draw any other cut where the cell needs it).
Source/drain columns alternate s, d, s, ... from the left (at x = 54, 108, ...).

Standard-cell row mode (`row`): the device is drawn in the coordinates of a 270 nm (7.5-track) cell
placed at y = 0, exactly like the library cells - nMOS on fins 1..nfin from the bottom, pMOS on
fins 8..9-nfin from the top, gates running to the middle of the cell (so an nMOS and a pMOS in the
same column form one continuous gate). Standalone (not row) devices extend their gates 70 nm past
the ACTIVE on both sides, room for a gate contact above or below.

Chaining (`abut_left` / `abut_right`): the dummy gate on that side is left out and the diffusion
runs on into the neighbour's, whose outer source/drain column coincides with this one's (devices
overlap by two gate pitches). The shared column keeps its contact unless `contact_left/right` is
off (e.g. the inner node of a series stack).

The standard-cell frame (`stdcell`): boundary, well/implant split, VT layer, the full fin grid,
M1 + LIG rails joined by V0 at every gate-pitch column, GCUT over them, and dummy gates at both cell
edges. A source connects to a rail by running its LISD into the LIG rail (LIG and LISD connect
where they overlap).
"""
import pya

from .asap7 import CONDUCTOR_STACK, DBU, LAYERS, NM, VIA_DEFS, VT_LAYER

LIBRARY = "OpenLayout_ASAP7"
CPP, FIN_PITCH, CELL_HEIGHT, MID = 54, 27, 270, 135
ROW_MAX_FINS = 3


def mos_geometry(kind: str, nfin: int, nf: int, vt: str = "rvt", row: bool = False,
                 abut_left: bool = False, abut_right: bool = False,
                 contact_left: bool = True, contact_right: bool = True) -> dict:
    """Shapes {layer: [(x1, y1, x2, y2) nm]} and terminals {term: [(x, y, layer)]} of one FinFET."""
    w = CPP * (nf + 2)
    gates = [27 + CPP * i for i in range(nf + 2)]           # gates[0] and gates[-1] are dummies
    real = gates[1:-1]
    dummies = ([] if abut_left else [gates[0]]) + ([] if abut_right else [gates[-1]])
    s = {name: [] for name in ("fin", "active", "gate", "lisd", "sdt")}
    terminals = {"g": [], "s": [], "d": []}

    if row:
        nfin = min(nfin, ROW_MAX_FINS)
        if kind == "nmos":
            fins = range(1, nfin + 1)
            gy = (-5, MID)                                     # gate from below the rail to mid-cell
            half, g_y = (0, 0, w, MID), MID - 14
        else:
            fins = range(9 - nfin, 9)
            gy = (MID, CELL_HEIGHT + 5)
            half, g_y = (0, MID, w, CELL_HEIGHT), MID + 14
        act_bot = FIN_PITCH * fins[0]                          # 10 nm below the lowest fin
        act_top = FIN_PITCH * (fins[-1] + 1)                   # 10 nm above the highest fin
        for c in real + dummies:
            s["gate"].append((c - 10, gy[0], c + 10, gy[1]))
        terminals["g"] = [(c, g_y, "gate") for c in real]
        implant = half
        bbox = half
    else:
        fins = range(1, nfin + 1)
        act_bot, act_top = 27, 27 * (nfin + 1)
        yb, yt = act_bot - 70, act_top + 70                    # room for a gate contact either side
        for c in real + dummies:
            s["gate"].append((c - 10, yb, c + 10, yt))
        terminals["g"] = [(c, (act_bot + act_top) / 2, "gate") for c in real]
        implant = (0, yb, w, yt)
        bbox = (0, yb, w, yt)

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


MOS_PARAMS = ("nfin", "nf", "vt", "row", "abut_left", "abut_right", "contact_left", "contact_right")


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
        # V0 joining each LIG rail to its M1 rail at every gate-pitch column, like the library cells
        "v0": [(CPP * k - 9, y - 9, CPP * k + 9, y + 9) for y in (0, CELL_HEIGHT) for k in range(1, cpp)],
    }
    if cpp >= 2:   # dummy gates on both cell edges, cut at mid-height like the library cells
        for c in (27, w - 27):
            s["gate"].append((c - 10, -5, c + 10, CELL_HEIGHT + 5))
            s["gcut"].append((c - 27, MID - 22, c + 27, MID + 22))
    if VT_LAYER.get(vt):
        s[VT_LAYER[vt]] = [(0, 0, w, CELL_HEIGHT)]
    return {"shapes": s, "rails": {"VSS": (0, 0), "VDD": (0, CELL_HEIGHT)}}


def via_levels(bottom: str, top: str) -> list:
    """Adjacent (lower, upper) pairs from bottom up to top, e.g. lisd-m3: (lisd, m1), (m1, m2), (m2, m3)."""
    if (bottom, top) in VIA_DEFS:
        return [(bottom, top)]
    if bottom not in ("lisd", "lig") + tuple(CONDUCTOR_STACK) or top not in CONDUCTOR_STACK:
        raise ValueError(f"no via from {bottom} to {top}")
    start = 0 if bottom in ("lisd", "lig") else CONDUCTOR_STACK.index(bottom) + 1
    stop = CONDUCTOR_STACK.index(top)
    if stop < start:
        raise ValueError(f"no via from {bottom} to {top}")
    pairs = [(bottom, CONDUCTOR_STACK[start])] if bottom in ("lisd", "lig") else []
    pairs += [(CONDUCTOR_STACK[i - 1], CONDUCTOR_STACK[i]) for i in range(max(start, 1), stop + 1)]
    return pairs


def via_geometry(bottom: str, top: str, rows: int = 1, cols: int = 1) -> dict:
    """Via (array, or stack of arrays) from bottom to top, centred on the origin: the cuts of each
    level with their pads on the layers below and above, sized as the LEF's default vias."""
    shapes = {}
    for lower, upper in via_levels(bottom, top):
        d = VIA_DEFS[(lower, upper)]
        x1, y1, x2, y2 = d["box"]
        w, h = x2 - x1, y2 - y1
        px, py = w + d["space"], h + d["space"]
        ox, oy = -(cols - 1) * px / 2, -(rows - 1) * py / 2       # array centred on the origin
        cuts = [(ox + c * px + x1, oy + r * py + y1, ox + c * px + x2, oy + r * py + y2)
                for r in range(rows) for c in range(cols)]
        shapes.setdefault(d["cut"], []).extend(cuts)
        ax1, ay1 = ox + x1, oy + y1
        ax2, ay2 = ox + (cols - 1) * px + x2, oy + (rows - 1) * py + y2
        for layer, (bx1, by1, bx2, by2) in ((lower, d["bottom"]), (upper, d["top"])):
            # the default pad's enclosure of the cut, around the whole array
            shapes.setdefault(layer, []).append((ax1 + (bx1 - x1), ay1 + (by1 - y1), ax2 + (bx2 - x2), ay2 + (by2 - y2)))
    return {"shapes": shapes, "terminals": {"t": [(0, 0, top)]}}


def via_choices() -> list:
    """[(title, "bottom-top")] of every via and via stack, single vias first."""
    singles = [(f"{d['cut'].upper()}  {b.upper()} → {t.upper()}   {d['box'][2] - d['box'][0]:g}×"
                f"{d['box'][3] - d['box'][1]:g} nm", f"{b}-{t}") for (b, t), d in VIA_DEFS.items()]
    stacks = []
    for b in ("lisd", "lig") + tuple(CONDUCTOR_STACK[:-1]):
        for t in CONDUCTOR_STACK:
            try:
                levels = via_levels(b, t)
            except ValueError:
                continue
            if len(levels) > 1:
                cuts = "+".join(VIA_DEFS[lv]["cut"].upper() for lv in levels)
                stacks.append((f"Stack  {b.upper()} → {t.upper()}  ({cuts})", f"{b}-{t}"))
    return singles + stacks


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
        draw(self.cell, mos_geometry(self.kind, self.nfin, self.nf, self.vt, self.row,
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
    """Via, via array or via stack, centred on its origin (ASAP7 default via sizes)."""
    PAIRS = [v for _, v in via_choices()]

    def __init__(self):
        super().__init__()
        self.param("layers", self.TypeString, "Via", default="lisd-m1",
                   choices=[[t, v] for t, v in via_choices()])
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
