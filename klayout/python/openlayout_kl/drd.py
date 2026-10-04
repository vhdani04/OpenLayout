"""Design-rule-driven editing, like Virtuoso's DRD in notify mode: while a shape is being drawn
(path, box) or moved, every gap between it and a neighbouring shape on the same layer that is
closer than the ASAP7 minimum spacing is outlined, with a dimension line labelled with the minimum
("18 nm min"). Nothing is constrained; the hints go away when the edit ends.

The spacing values are the DRC deck's (docs/DRC.md), per layer:
  lines  - LISD, LIG, M1-M3, M8-M9: by the lengths of the facing edges (long side vs. line end,
           and line-end width classes), plus corner-to-corner where the DRM has it
  hv     - a horizontal and a vertical spacing (WELL, ACTIVE, GATE, SDT, GCUT, M4-M7)
  plain  - one value (vias)
Shapes that touch or overlap the edited shape are on its net and are not checked.
"""
import math

import pya

from .asap7 import LAYER_NAME

# (kind, values ...) in nm
#   lines: (long edge threshold, side-side, tip-side, tip-tip >= 24, tip-tip < 24, tip-tip mixed, corner)
RULES = {
    "lisd": ("lines", 36, 18, 25, 27, 27, 27, None),
    "lig": ("lines", 36, 18, 25, 27, 31, 31, None),
    "m1": ("lines", 36, 18, 25, 27, 31, 31, 20),
    "m2": ("lines", 36, 18, 25, 27, 31, 31, 20),
    "m3": ("lines", 36, 18, 25, 27, 31, 31, 20),
    "m8": ("lines", 79.9, 40, 43, 46, 46, 46, None),
    "m9": ("lines", 79.9, 40, 43, 46, 46, 46, None),
    #   hv: (horizontal spacing, vertical spacing); None = no rule that way
    "well": ("hv", 54, 108),
    "active": ("hv", 38, 27),
    "gate": ("hv", 34, 54),
    "sdt": ("hv", 30, None),
    "gcut": ("hv", None, 35),
    "m4": ("hv", 40, 24),
    "m5": ("hv", 24, 40),
    "m6": ("hv", 40, 32),
    "m7": ("hv", 32, 40),
    #   plain: (spacing, corner-to-corner)
    "v0": ("plain", 18, 23),
    "v1": ("plain", 18, 23),
    "v2": ("plain", 18, 23),
    "v3": ("plain", 18, 23),
    "v4": ("plain", 33, 33),
    "v5": ("plain", 33, 33),
    "v6": ("plain", 45, 45),
    "v7": ("plain", 45, 45),
    "v8": ("plain", 57, 57),
}
MAX_RULE = 120          # nm: how far around the edited shape to look
MAX_HINTS = 12
COLOR = 0xFF3B30        # the gap outline
enabled = True


def rule_for(layout, li):
    info = layout.get_info(li)
    if info.datatype != 0:
        return None, None
    name = LAYER_NAME.get(info.layer)
    return name, RULES.get(name)


def required(spec, len_a, len_b, horizontal_gap):
    """Minimum spacing (nm) between two facing edges of lengths len_a / len_b (nm)."""
    kind = spec[0]
    if kind == "lines":
        _, long_th, side, tip_side, tt_wide, tt_narrow, tt_mixed, _ = spec
        la, lb = len_a > long_th, len_b > long_th
        if la and lb:
            return side
        if la or lb:
            return tip_side
        wa, wb = len_a >= 24, len_b >= 24
        return tt_wide if wa and wb else tt_narrow if not (wa or wb) else tt_mixed
    if kind == "hv":
        return spec[1] if horizontal_gap else spec[2]
    return spec[1]


def corner_rule(spec):
    return spec[7] if spec[0] == "lines" else spec[2] if spec[0] == "plain" else None


def _outward(poly, e):
    """unit outward normal of polygon edge e"""
    d = pya.DVector(e.dx(), e.dy())
    n = pya.DVector(-d.y, d.x) * (1.0 / d.length())
    mid = pya.DPoint((e.p1.x + e.p2.x) / 2, (e.p1.y + e.p2.y) / 2)
    return n * -1.0 if poly.inside(mid + n * 0.0001) else n


def violations(moving, static, spec):
    """Gaps between the moving polygons and the static ones (DPolygon, um) under the minimum.
    Returns [(gap DBox, p1, p2, required nm, actual nm)]."""
    out = []
    corner = corner_rule(spec)
    for mp in moving:
        medges = [(e, _outward(mp, e)) for e in mp.each_edge() if e.dx() == 0 or e.dy() == 0]
        for sp in static:
            sedges = [(e, _outward(sp, e)) for e in sp.each_edge() if e.dx() == 0 or e.dy() == 0]
            for ea, na in medges:
                for eb, nb in sedges:
                    if abs(na.x + nb.x) > 1e-9 or abs(na.y + nb.y) > 1e-9:
                        continue                           # not facing each other
                    horizontal = abs(na.x) > 0.5            # vertical edges: a horizontal gap
                    if horizontal:
                        gap = (eb.p1.x - ea.p1.x) * na.x
                        lo = max(min(ea.p1.y, ea.p2.y), min(eb.p1.y, eb.p2.y))
                        hi = min(max(ea.p1.y, ea.p2.y), max(eb.p1.y, eb.p2.y))
                    else:
                        gap = (eb.p1.y - ea.p1.y) * na.y
                        lo = max(min(ea.p1.x, ea.p2.x), min(eb.p1.x, eb.p2.x))
                        hi = min(max(ea.p1.x, ea.p2.x), max(eb.p1.x, eb.p2.x))
                    if gap <= 1e-9 or hi - lo <= 1e-9:
                        continue
                    req = required(spec, ea.length() * 1000, eb.length() * 1000, horizontal)
                    if req is None or gap * 1000 >= req - 1e-6:
                        continue
                    mid = (lo + hi) / 2
                    if horizontal:
                        x1, x2 = ea.p1.x, eb.p1.x
                        box = pya.DBox(min(x1, x2), lo, max(x1, x2), hi)
                        p1, p2 = pya.DPoint(x1, mid), pya.DPoint(x2, mid)
                    else:
                        y1, y2 = ea.p1.y, eb.p1.y
                        box = pya.DBox(lo, min(y1, y2), hi, max(y1, y2))
                        p1, p2 = pya.DPoint(mid, y1), pya.DPoint(mid, y2)
                    out.append((box, p1, p2, req, gap * 1000))
            if corner:
                out += _corner_violations(mp, sp, corner)
    out.sort(key=lambda v: v[4] - v[3])
    return out


def _corner_violations(mp, sp, corner):
    """corner-to-corner: the shapes' boxes do not overlap in x or y and their closest corners are
    nearer than the rule (both shapes rectangles - the usual case for wires and vias)"""
    a, b = mp.bbox(), sp.bbox()
    if not (mp.is_box() and sp.is_box()):
        return []
    dx = max(b.left - a.right, a.left - b.right)
    dy = max(b.bottom - a.top, a.bottom - b.top)
    if dx <= 1e-9 or dy <= 1e-9:
        return []
    d = math.hypot(dx, dy) * 1000
    if d >= corner - 1e-6:
        return []
    ax = a.right if b.left >= a.right else a.left
    ay = a.top if b.bottom >= a.top else a.bottom
    bx = b.left if b.left >= a.right else b.right
    by = b.bottom if b.bottom >= a.top else b.top
    p1, p2 = pya.DPoint(ax, ay), pya.DPoint(bx, by)
    return [(pya.DBox(p1, p2), p1, p2, corner, d)]


def static_polygons(cell, li, window, skip=None):
    """Merged shapes of layer li under cell touching window (um), as DPolygons (um).
    skip(iterator) -> True leaves a shape out (the originals of shapes being moved)."""
    layout = cell.layout()
    dbu = layout.dbu
    reg = pya.Region()
    it = cell.begin_shapes_rec_touching(li, window)
    while not it.at_end():
        s = it.shape()
        if (s.is_box() or s.is_polygon() or s.is_path()) and not (skip and skip(it)):
            reg.insert(s.polygon.transformed(it.trans()))
        it.next()
    return [p.to_dtype(dbu) for p in reg.merged().each()]


def check(cell, li, moving, skip=None):
    """Violations of the moving polygons (DPolygon, um, cell coordinates) against layer li."""
    layout = cell.layout()
    name, spec = rule_for(layout, li)
    if spec is None or not moving:
        return []
    dbu = layout.dbu
    mreg = pya.Region([p.to_itype(dbu) for p in moving]).merged()
    mpolys = [p.to_dtype(dbu) for p in mreg.each()]
    window = mreg.bbox().to_dtype(dbu).enlarged(MAX_RULE / 1000, MAX_RULE / 1000)
    static = [sp for sp in static_polygons(cell, li, window, skip)
              if not pya.Region(sp.to_itype(dbu)).interacting(mreg).count()]   # touching = same net
    return violations(mpolys, static, spec)


class Display:
    """The hints of one view: gap outlines (markers) and labelled dimension lines (rulers)."""

    def __init__(self, view):
        self.view = view
        self.markers = []
        self.rulers = []

    def clear(self):
        self.markers = []
        for a in self.rulers:
            try:
                if a.is_valid():
                    a.delete()
            except Exception:
                pass
        self.rulers = []

    def show(self, hits, trans=None):
        self.clear()
        t = trans or pya.DCplxTrans()
        for box, p1, p2, req, actual in hits[:MAX_HINTS]:
            m = pya.Marker(self.view)
            m.color = COLOR
            m.frame_color = COLOR
            m.line_width = 2
            m.vertex_size = 0
            m.dither_pattern = 5
            m.set(t * box)
            self.markers.append(m)
            a = pya.Annotation()
            a.p1, a.p2 = t * p1, t * p2
            a.fmt = f"{req:g} nm min"
            a.style = pya.Annotation.StyleArrowBoth
            a.outline = pya.Annotation.OutlineDiag
            a.category = "_openlayout_drd"
            self.view.insert_annotation(a)
            self.rulers.append(a)


_displays = {}


def display(view):
    key = id(view)
    if key not in _displays:
        _displays[key] = Display(view)
    return _displays[key]


def show(view, cell, li, moving, skip=None, trans=None):
    """Check and show (or clear) the hints for shapes being edited in `cell` on layer li."""
    return show_layers(view, cell, {li: moving}, skip, trans)


def show_layers(view, cell, moving, skip=None, trans=None):
    """As show, for {layer index: [DPolygon]} (e.g. a moved transistor's layers)."""
    d = display(view)
    if not enabled:
        d.clear()
        return []
    hits = []
    try:
        for li, polys in moving.items():
            hits += check(cell, li, polys, skip)
    except Exception as e:          # a hint must never break editing
        print(f"OpenLayout DRD: {e}")
        hits = []
    hits.sort(key=lambda v: v[4] - v[3])
    d.show(hits, trans)
    if hits:
        mw = pya.Application.instance().main_window()
        if mw is not None:
            worst = hits[0]
            mw.message(f"DRD: {len(hits)} spacing(s) under the minimum - {worst[4]:.1f} nm where "
                       f"{worst[3]:g} nm is needed", 2000)
    return hits


def clear(view):
    display(view).clear()


def set_enabled(on: bool):
    """OpenLayout > DRD Spacing Hints"""
    global enabled
    enabled = bool(on)
    if not enabled:
        for d in _displays.values():
            d.clear()
