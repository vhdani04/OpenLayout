"""Layer Grid: each layer's legal track grid drawn over the layout (OpenLayout > Show Layer Grid…).

The grid is not typed in here: grid_table() reads it from the PDK files every time, and a layer
whose grid the sources do not pin down is listed as such and not drawn.

- FIN, GATE, M4-M7: the OpenLayout DRC deck (pdk/asap7/klayout/drc/asap7.drc), which checks the
  DRM's exact-pitch and on-track rules - FIN.S.1 (27 nm), GATE.S.1 (54 nm), M4/M6.AUX.2 (minimum
  width wires on tracks 2 x width apart, offset 0; M5 / M7 the same, vertically). These are DRC
  rules: a wire off them is an error.
- M1, M2, M3: no DRM grid rule; the tracks are the place-and-route tracks of the ASAP7 tech LEF
  (techlef_misc/asap7_tech_1x_201209.lef: DIRECTION, PITCH, OFFSET; M2 per cell row with
  LEF58_PITCH FIRSTLASTPITCH, the row height from the library LEF's SITE). Drawn dashed.
- M8, M9: the LEF gives the pitch (80 nm) but no OFFSET and the DRM has no grid rule: not drawn.

Every grid is in the coordinates of the cell being edited (the DRC checks that cell flat, from its
origin) and is mapped into the view through the cell view's context when a cell is descended into.
The lines are markers, not shapes: they are not selectable and never reach the layout. They are
redrawn a moment after the view is zoomed or panned; a layer whose tracks would be closer than
MIN_PX pixels on screen is left out until the view is zoomed in.
"""
import glob
import math
import os
import re
from pathlib import Path

import pya

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))
DRC_DECK = FLOW / "pdk" / "asap7" / "klayout" / "drc" / "asap7.drc"
STDCELLS = Path(os.environ.get("ASAP7_STDCELLS", Path.home() / "openlayout/pdk/asap7/asap7sc7p5t_28"))
TECH_LEF = "asap7_tech_1x_201209.lef"     # the library's own tech LEF (techlef_misc)

ORDER = ["fin", "gate", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9"]
COLORS = {"fin": 0x58C4DD, "gate": 0xE5484D, "m1": 0x4FA3FF, "m2": 0xE8B04B, "m3": 0x4CC38A,
          "m4": 0xC678DD, "m5": 0xF2834F, "m6": 0x2EC4B6, "m7": 0xF06BAA, "m8": 0xA3BE8C, "m9": 0xB4A7F5}
MIN_PX = 5                # tracks closer than this on screen are not drawn (zoom in)
MAX_LINES = 600           # per layer and redraw
REDRAW_MS = 60
SOLID, DASHED = 0, 2      # KLayout line styles: DRC rule / router tracks only


class Grid:
    """One layer's tracks: centrelines at offset + k * pitch (um), or, with row = (height, [y]),
    at r * height + y for every cell row r. horizontal: the lines run along x (constant y)."""

    def __init__(self, key, horizontal=None, pitch=None, offset=None, width=None, row=None,
                 kind="none", source="", note=""):
        self.key, self.horizontal, self.pitch, self.offset = key, horizontal, pitch, offset
        self.width, self.row, self.kind, self.source, self.note = width, row, kind, source, note

    @property
    def drawable(self):
        return self.kind in ("drc", "lef")

    @property
    def spacing(self):
        """the smallest distance between two tracks (um)"""
        if self.row:
            ys = self.row[1]
            return min(b - a for a, b in zip(ys, ys[1:])) if len(ys) > 1 else self.row[0]
        return self.pitch

    def positions(self, lo, hi):
        """track coordinates (um) in [lo, hi]"""
        if not self.drawable:
            return []
        if self.row:
            h, ys = self.row
            out = []
            for r in range(math.floor(lo / h) - 1, math.ceil(hi / h) + 1):
                out += [round(r * h + y, 6) for y in ys if lo <= r * h + y <= hi]
            return out
        k0 = math.ceil((lo - self.offset) / self.pitch - 1e-9)
        k1 = math.floor((hi - self.offset) / self.pitch + 1e-9)
        return [round(self.offset + k * self.pitch, 6) for k in range(k0, k1 + 1)]

    def on_grid(self, c, tol=1e-4):
        """is the coordinate c (um) a track?"""
        return any(abs(p - c) < tol for p in self.positions(c - 2 * tol, c + 2 * tol))

    def describe(self):
        nm = lambda v: f"{v * 1000:g}"
        if not self.drawable:
            return "position undetermined" + (f" (pitch {nm(self.pitch)} nm)" if self.pitch else "")
        d = "horizontal" if self.horizontal else "vertical"
        if self.row:
            h, ys = self.row
            where = f"y = {nm(ys[0])} + {nm(self.pitch)}k nm, {len(ys)} per {nm(h)} nm row"
        else:
            axis = "y" if self.horizontal else "x"
            where = f"{axis} = {nm(self.offset)} + {nm(self.pitch)}k nm"
        return f"{d}, {where}; min width {nm(self.width)} nm"


# ---- reading the sources -------------------------------------------------------------------------
def _num(s):
    return float(s)


def lef_layers(path):
    """{layer name: {direction, pitch: (x, y), offset, width, firstlast}} from a tech LEF"""
    text = re.sub(r"#[^\n]*", "", Path(path).read_text())
    out = {}
    for m in re.finditer(r"^LAYER\s+(\S+)\s*\n(.*?)^END\s+\1\b", text, re.S | re.M):
        name, body = m.group(1), m.group(2)
        props = dict(re.findall(r'PROPERTY\s+(\w+)\s*"(.*?)"\s*;', body, re.S))
        body = re.sub(r'PROPERTY\s+\w+\s*".*?"\s*;', "", body, flags=re.S)
        info = {}
        d = re.search(r"^\s*DIRECTION\s+(\w+)\s*;", body, re.M)
        if d:
            info["direction"] = d.group(1).upper()
        p = re.search(r"^\s*PITCH\s+([\d.]+)(?:\s+([\d.]+))?\s*;", body, re.M)
        if p:
            info["pitch"] = (_num(p.group(1)), _num(p.group(2) or p.group(1)))
        o = re.search(r"^\s*OFFSET\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\s*;", body, re.M)
        if o:
            info["offset"] = (_num(o.group(1)), _num(o.group(2) or o.group(1)))
        w = re.search(r"^\s*WIDTH\s+([\d.]+)\s*;", body, re.M)
        if w:
            info["width"] = _num(w.group(1))
        fl = re.search(r"PITCH\s+([\d.]+)\s+FIRSTLASTPITCH\s+([\d.]+)", props.get("LEF58_PITCH", ""))
        if fl:
            info["firstlast"] = (_num(fl.group(1)), _num(fl.group(2)))
        out[name.upper()] = info
    return out


def lef_site(path):
    """(width, height) um of the library's core SITE"""
    m = re.search(r"^SITE\s+\S+.*?SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", Path(path).read_text(), re.S | re.M)
    return (_num(m.group(1)), _num(m.group(2))) if m else None


def drc_grids(path):
    """the grid rules of the OpenLayout DRC deck: {layer: (horizontal, pitch, offset, width, rule)}"""
    text = Path(path).read_text()
    out = {}
    # FIN.S.1: (b + t - n(27)) % n(54) == 0  ->  centre (b + t) / 2 on 27 / 2 + 54 / 2 * k
    m = re.search(r"bad_boxes\(fin_r\)\s*\{[^}]*\(b \+ t - n\((\d+(?:\.\d+)?)\)\) % n\((\d+(?:\.\d+)?)\) == 0", text)
    w = re.search(r"fin_r\.without_bbox_height\((\d+(?:\.\d+)?)\.nm\)", text)          # FIN.W.1, exact
    if m and w:
        out["fin"] = (True, _num(m.group(2)) / 2000, _num(m.group(1)) / 2000, _num(w.group(1)) / 1000, "FIN.S.1")
    m = re.search(r"bad_boxes\(gate_r\)\s*\{[^}]*\(l \+ r - n\((\d+(?:\.\d+)?)\)\) % n\((\d+(?:\.\d+)?)\) == 0", text)
    w = re.search(r"gate_r\.without_bbox_width\((\d+(?:\.\d+)?)\.nm\)", text)       # GATE.W.1, exact
    if m and w:
        out["gate"] = (False, _num(m.group(2)) / 2000, _num(m.group(1)) / 2000, _num(w.group(1)) / 1000, "GATE.S.1")
    # M4-M7: minimum-width wires start (bottom / left edge) on 2 * w * k -> centres at w / 2 + 2 * w * k
    if "start.call(*c) % n(2 * w) == 0" in text:
        for nm, lay, w, horizontal in re.findall(r'^track_metal\("(M\d)", (\w+), (\d+), \d+, \d+, (true|false)\)', text, re.M):
            w = _num(w) / 1000
            out[lay] = (horizontal == "true", 2 * w, w / 2, w, f"{nm}.AUX.2")
    return out


def tech_lef_path():
    p = STDCELLS / "techlef_misc" / TECH_LEF
    if p.is_file():
        return p
    found = sorted(glob.glob(str(STDCELLS / "techlef_misc" / "asap7_tech_1x_*.lef")))
    return Path(found[0]) if found else None


def cell_lef_path():
    found = sorted(glob.glob(str(STDCELLS / "LEF" / "asap7sc7p5t_*_R_1x_*.lef"))) or \
        sorted(glob.glob(str(STDCELLS / "LEF" / "asap7sc7p5t_*_1x_*.lef")))
    return Path(found[0]) if found else None


_table = None


def grid_table(reload=False):
    """{layer: Grid} for ORDER, from the DRC deck and the tech / library LEF"""
    global _table
    if _table is not None and not reload:
        return _table
    drc = drc_grids(DRC_DECK) if DRC_DECK.is_file() else {}
    lef_path, site_path = tech_lef_path(), cell_lef_path()
    lef = lef_layers(lef_path) if lef_path else {}
    site = lef_site(site_path) if site_path else None
    lef_name = lef_path.name if lef_path else "tech LEF (not found)"
    table = {}
    for key in ORDER:
        L = lef.get(key.upper(), {})
        if key in drc:
            horizontal, pitch, offset, width, rule = drc[key]
            g = Grid(key, horizontal, pitch, offset, width, kind="drc",
                     source=f"DRC deck {DRC_DECK.name}, {rule} (DRM r1p7)")
            if L.get("pitch"):
                lp = L["pitch"][1] if horizontal else L["pitch"][0]
                lo = L.get("offset")
                lo = None if lo is None else (lo[1] if horizontal else lo[0])
                if abs(lp - pitch) > 1e-9 or lo is None or abs(lo - offset) > 1e-9:
                    g.note = (f"{lef_name}: PITCH {lp * 1000:g} nm, "
                              + ("no OFFSET" if lo is None else f"OFFSET {lo * 1000:g} nm")
                              + " - the DRC rule is used")
            table[key] = g
            continue
        if not L.get("direction") or not L.get("pitch"):
            table[key] = Grid(key, note=f"no grid rule in the DRC deck or DRM, no tracks in {lef_name}")
            continue
        horizontal = L["direction"] == "HORIZONTAL"
        pitch = L["pitch"][1] if horizontal else L["pitch"][0]
        width = L.get("width")
        src = f"{lef_name}: LAYER {key.upper()} DIRECTION / PITCH"
        if L.get("firstlast"):
            if not site:
                table[key] = Grid(key, horizontal, pitch, width=width,
                                  note="per-row tracks (FIRSTLASTPITCH) but no library SITE for the row height")
                continue
            p, first = L["firstlast"]
            h = site[1]
            n = round((h - 2 * first) / p) + 1
            ys = [round(first + i * p, 6) for i in range(n)]
            if n < 1 or abs(ys[-1] + first - h) > 1e-6:
                table[key] = Grid(key, horizontal, pitch, width=width,
                                  note=f"FIRSTLASTPITCH {first * 1000:g} / PITCH {p * 1000:g} do not fill a {h * 1000:g} nm row")
                continue
            table[key] = Grid(key, horizontal, p, width=width, row=(h, ys), kind="lef",
                              source=f"{lef_name}: LEF58_PITCH {p * 1000:g} FIRSTLASTPITCH {first * 1000:g}; "
                                     f"row height {h * 1000:g} nm (SITE in {site_path.name})",
                              note="router tracks only (the DRM has no grid rule for this layer)")
            continue
        if L.get("offset") is None:
            table[key] = Grid(key, horizontal, pitch, width=width,
                              note=f"{lef_name} gives PITCH {pitch * 1000:g} nm but no OFFSET, and the DRM "
                                   f"has no grid rule: track positions undetermined")
            continue
        offset = L["offset"][1] if horizontal else L["offset"][0]
        table[key] = Grid(key, horizontal, pitch, offset, width, kind="lef", source=src + " / OFFSET",
                          note="router tracks only (the DRM has no grid rule for this layer)")
    _table = table
    return table


# ---- drawing ---------------------------------------------------------------------------------------
_shown = set()
_listeners = []
_painter = None


def shown():
    return set(_shown)


def show(keys):
    """draw these layers' grids (replaces the current set)"""
    table = grid_table()
    _shown.clear()
    _shown.update(k for k in keys if k in table and table[k].drawable)
    painter().redraw()


def set_layer(key, on):
    keys = shown()
    (keys.add if on else keys.discard)(key)
    show(keys)


def clear():
    show([])


def on_change(fn):
    _listeners.append(fn)


def painter():
    global _painter
    if _painter is None:
        _painter = Painter(pya.Application.instance().main_window())
    return _painter


class Painter:
    """Draws the shown grids as markers in the current view; redraws when the view moves."""

    def __init__(self, mw):
        self.mw = mw
        self.markers = []
        self.lines = []          # (layer, DEdge in view coordinates) as drawn
        self.hidden = []         # layers too dense to draw at this zoom
        self.view = None
        self._views = set()
        self.timer = pya.QTimer(mw)
        self.timer.singleShot = True
        self.timer.interval = REDRAW_MS
        self.timer.timeout = self.redraw
        mw.on_current_view_changed += self.schedule

    def schedule(self):
        self.timer.start()

    def _watch(self, view):
        if id(view) not in self._views:
            self._views.add(id(view))
            view.on_viewport_changed += self.schedule
            view.on_active_cellview_changed += self.schedule

    def clear_markers(self):
        for m in self.markers:
            try:
                m._destroy()
            except Exception:
                pass
        self.markers, self.lines = [], []

    def redraw(self):
        self.clear_markers()
        self.hidden = []
        view = self.mw.current_view()
        if view is not None:
            self._watch(view)
        cv = view.active_cellview() if view is not None else None
        if _shown and cv is not None and cv.is_valid():
            self.draw(view, cv)
        for fn in list(_listeners):
            try:
                fn()
            except RuntimeError:          # its widget is gone
                _listeners.remove(fn)

    def draw(self, view, cv):
        ctx = cv.context_dtrans()                          # edited cell -> view (context) coordinates
        vbox = view.box()
        # a margin of one view each way: a small pan shows lines until the redraw catches up
        area = vbox.enlarged(pya.DVector(vbox.width(), vbox.height()))
        cbox = ctx.inverted() * area                       # the same area in the cell's coordinates
        px_per_um = view.viewport_trans().mag
        table = grid_table()
        for key in ORDER:
            if key not in _shown:
                continue
            g = table[key]
            if g.spacing * px_per_um < MIN_PX:
                self.hidden.append(key)
                continue
            lo, hi = (cbox.bottom, cbox.top) if g.horizontal else (cbox.left, cbox.right)
            ps = g.positions(lo, hi)
            if len(ps) > 3 * MAX_LINES:
                self.hidden.append(key)
                continue
            for c in ps:
                e = pya.DEdge(cbox.left, c, cbox.right, c) if g.horizontal else pya.DEdge(c, cbox.bottom, c, cbox.top)
                e = ctx * e
                m = pya.Marker(view)
                m.set(e)
                m.color = COLORS[key]
                m.frame_color = COLORS[key]
                m.line_width = 1
                m.line_style = SOLID if g.kind == "drc" else DASHED
                m.vertex_size = 0
                m.halo = 0
                m.dismissable = False
                self.markers.append(m)
                self.lines.append((key, e))


# ---- the window ------------------------------------------------------------------------------------
def _hex(c):
    return f"#{c:06x}"


class LayerGridForm(pya.QDialog):
    """Checkboxes per layer; a ticked layer's tracks are drawn at once. Non-modal."""

    def __init__(self, parent, ui):
        super().__init__(parent)
        self.ui = ui
        self.windowTitle = "Layer Grid"
        table = grid_table()
        lay = pya.QVBoxLayout(self)
        intro = pya.QLabel("Where each layer may be routed, from the ASAP7 DRC deck and tech LEF. "
                           "Solid: DRC rule; dashed: router tracks only. Grids are in the edited cell's "
                           "coordinates. Hover a layer for its source.", self)
        intro.wordWrap = True
        intro.styleSheet = f"color: {ui['dim']};"
        lay.addWidget(intro)
        grid = pya.QGridLayout()
        self.boxes = {}
        for i, key in enumerate(ORDER):
            g = table[key]
            cb = pya.QCheckBox(key.upper() if key.startswith("m") else key.capitalize(), self)
            cb.enabled = g.drawable
            cb.checked = key in _shown
            cb.toggled = lambda on, k=key: set_layer(k, on)
            swatch = pya.QLabel("", self)
            swatch.setFixedSize(22, 4)
            swatch.styleSheet = (f"background: {_hex(COLORS[key])};" if g.drawable else f"background: {ui['border']};")
            text = g.describe()
            info = pya.QLabel(text if g.drawable else "not drawn: " + text, self)
            info.styleSheet = f"color: {ui['text'] if g.drawable else ui['warn']};"
            tip = "\n".join(s for s in (g.source, g.note) if s)
            for w in (cb, info):
                w.toolTip = tip
            grid.addWidget(cb, i, 0)
            grid.addWidget(swatch, i, 1)
            grid.addWidget(info, i, 2)
            self.boxes[key] = cb
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        self.status = pya.QLabel("", self)
        self.status.styleSheet = f"color: {ui['dim']};"
        lay.addWidget(self.status)
        bar = pya.QHBoxLayout()
        for label, slot in (("All", self.all), ("Clear", self.clear)):
            b = pya.QPushButton(label, self)
            b.clicked = slot
            bar.addWidget(b)
        bar.addStretch(1)
        close = pya.QPushButton("Close", self)
        close.clicked = lambda: self.hide()
        bar.addWidget(close)
        lay.addLayout(bar)
        self.resize(600, 470)
        on_change(self.sync)
        self.sync()

    def all(self):
        show([k for k, g in grid_table().items() if g.drawable])

    def clear(self):
        clear()

    def sync(self):
        """follow the shown set and say which layers are too dense at this zoom"""
        for key, cb in self.boxes.items():
            want = key in _shown
            if cb.checked != want:
                cb.blockSignals(True)
                cb.checked = want
                cb.blockSignals(False)
        hidden = painter().hidden
        self.status.text = (f"Zoom in to see: {', '.join(k.upper() for k in hidden)}" if hidden else "")


_form = None


def open_form(mw, ui):
    """OpenLayout > Show Layer Grid…: the (single, non-modal) Layer Grid window"""
    global _form
    painter()
    if _form is None:
        _form = LayerGridForm(mw, ui)
    _form.show()
    _form.raise_()
    _form.activateWindow()
    return _form
