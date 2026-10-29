"""Place Pins: the pins of whole buses in one go, instead of one by one.

The pins to place are named like the schematic's ports (the schematic link <cell>.ol.json): a bus
by its base name ("BL" - every BL[i] port, in the schematic's order), a range ("BL[7:0]",
"BL<3:0>"), a single bit or a plain pin. Each bit becomes a Generate Layout pin (generate._add_pin:
a square of the metal's minimum width on its pin purpose, with the label), put down where:

  terminals  on the net's own terminal - the pin of the sub-cell (or transistor) the net connects
             to, at the end of that pin shape nearest the chosen edge. The pin sits on drawn metal
             of the net, so it connects for LVS and DRC (OL.PIN) is clean without any wiring.
  wires      on the end of the net's wiring on the chosen metal nearest the chosen edge - route the
             bus out first, then drop all its pins on the wire ends (flat extraction: wires in
             sub-cells count too).
  edge       along a side of the cell (its boundary), the pin flush inside it: at the net's
             terminals' position along the side ("aligned": a bit line's pin right above its bit
             line) or evenly spaced at a pitch, in port order.

On M4 - M7 (SADP: minimum-width wires on absolute routing tracks, low edge at 2 * w * k) edge pins
are snapped onto the tracks of their metal. Pins that exist already are moved (replace=True) or
left alone. Pins that end up too close to another pin of the same metal, or not on drawn metal of
their layer (DRC OL.PIN: draw the wire to them), are reported.

Batch (e.g. klayout -b -r script.py):
    from openlayout_kl import pin_place
    pin_place.place_pins_file("cell.gds", ["BL", "BLB"], mode="edge", edge="top", metal="m3")
In the GUI: OpenLayout > Place Pins… (pin_place_form.py), one undo step.
"""
import re

import pya

from . import connectivity
from .asap7 import LAYERS, METALS, MIN_WIDTH, PIN

MODES = ("terminals", "wires", "edge")
EDGES = ("top", "bottom", "left", "right")
VERTICAL = {"m1", "m3", "m5", "m7", "m9"}          # routing direction; M2, M4, M6, M8 run horizontally
TRACKS = {"m4": 48, "m5": 48, "m6": 64, "m7": 64}   # SADP track pitch (nm): wires' low edge at k * pitch
PITCH = {"m1": 36, "m2": 36, "m3": 36, "m4": 48, "m5": 48, "m6": 64, "m7": 64, "m8": 80, "m9": 80}
BIT_RE = re.compile(r"^(?P<base>.+)\[(?P<i>\d+)\]$")


# ---- names ---------------------------------------------------------------------------------------

def _expand(name):
    from .generate import _flow_python
    _flow_python()
    from openlayout.buses import expand
    return expand(name)


def bus_groups(ports):
    """[(group name, [bits])] of the ports, in port order: a bus's bits under its base name (BL),
    a plain pin on its own."""
    groups = {}
    for p in ports:
        m = BIT_RE.match(p)
        groups.setdefault(m["base"] if m else p, []).append(p)
    return list(groups.items())


def resolve(names, ports=None):
    """(bits, unknown): the pin bits the names stand for (see the module doc), without repeats;
    with the link's ports, names that are no port are returned as unknown."""
    bits, unknown = [], []
    groups = dict(bus_groups(ports)) if ports else {}
    for name in names:
        name = name.strip()
        if not name:
            continue
        if name in groups:
            got = groups[name]
        else:
            got = _expand(name)
            if ports:
                unknown += [b for b in got if b not in ports]
                got = [b for b in got if b in ports]
        bits += [b for b in got if b not in bits]
    return bits, unknown


# ---- geometry (database units) -----------------------------------------------------------------

def cell_frame(top):
    """The cell's outline (Box, dbu): its boundary, else its sub-cells' boundaries, else its bbox."""
    layout = top.layout()
    li = layout.find_layer(LAYERS["boundary"], 0)
    if li is not None:
        if not top.shapes(li).is_empty():
            return top.shapes(li).bbox()
        r = pya.Region(top.begin_shapes_rec(li))
        if not r.is_empty():
            return r.bbox()
    return top.bbox()


def _end(poly, edge, w):
    """(along, across, gap): where a pin of width w goes at the end of the shape nearest the edge
    side - the centre of the shape's last w across that way - and that end's coordinate."""
    b = poly.bbox()
    if edge == "top":
        cut = pya.Box(b.left, b.top - w, b.right, b.top)
    elif edge == "bottom":
        cut = pya.Box(b.left, b.bottom, b.right, b.bottom + w)
    elif edge == "right":
        cut = pya.Box(b.right - w, b.bottom, b.right, b.top)
    else:
        cut = pya.Box(b.left, b.bottom, b.left + w, b.top)
    piece = (pya.Region(poly) & pya.Region(cut)).bbox()
    if piece.empty():
        piece = b
    c = piece.center()
    if edge in ("top", "bottom"):
        return c.x, (b.top - w // 2 if edge == "top" else b.bottom + w // 2), (b.top if edge == "top" else b.bottom)
    return c.y, (b.right - w // 2 if edge == "right" else b.left + w // 2), (b.right if edge == "right" else b.left)


def _gap(frame, edge, end):
    """How far a shape's end lies inside the frame's side (smaller = nearer the edge)."""
    return {"top": frame.top - end, "bottom": end - frame.bottom,
            "right": frame.right - end, "left": end - frame.left}[edge]


def _point(edge, along, across):
    return pya.Point(along, across) if edge in ("top", "bottom") else pya.Point(across, along)


def _nearest_end(polys, frame, edge, w):
    """(gap, point, edge) of the end of the shapes nearest the edge (edge "auto": nearest any side)."""
    best = None
    for poly in polys:
        for e in (EDGES if edge == "auto" else (edge,)):
            along, across, end = _end(poly, e, w)
            key = _gap(frame, e, end)
            if best is None or key < best[0]:
                best = (key, _point(e, along, across), e)
    return best or (None, None, None)


def _snap_track(v, metal, dbu, mode="nearest"):
    """A minimum-width wire's centre coordinate (dbu, across the metal's direction) onto its tracks."""
    pitch = TRACKS[metal] / 1000 / dbu
    half = MIN_WIDTH[metal] / 2000 / dbu
    k = (v - half) / pitch
    k = {"nearest": round(k), "down": int(k // 1), "up": -int(-k // 1)}[mode]
    return int(round(k * pitch + half))


# ---- what the nets have --------------------------------------------------------------------------

def _pin_shapes(top, metal):
    """[Polygon] of the metal's pin-purpose shapes inside the sub-cells (top coordinates), and
    its drawn shapes there: the sub-cells' pins, and the wires their labels may sit on instead."""
    layout = top.layout()
    out = {}
    for dt in (PIN, 0):
        li = layout.find_layer(LAYERS[metal], dt)
        polys = []
        if li is not None:
            it = top.begin_shapes_rec(li)
            it.min_depth = 1
            while not it.at_end():
                s = it.shape()
                if not s.is_text() and s.polygon is not None:
                    polys.append(s.polygon.transformed(it.trans()))
                it.next()
        out[dt] = polys
    return out


def terminal_shapes(layout, top, conn):
    """{net: [(metal, Polygon)]}: for every instance terminal on a metal, the pin shape its label is
    on (else the drawn shape, else a minimum-width square at the label), in top coordinates."""
    terms, _ = connectivity.terminals(layout, top, conn)
    shapes = {}
    out = {}
    for t in terms:
        if t.owner is None or t.layer not in METALS:
            continue
        if t.layer not in shapes:
            shapes[t.layer] = _pin_shapes(top, t.layer)
        p = pya.Point.from_dpoint(t.point * (1 / layout.dbu)) if hasattr(pya.Point, "from_dpoint") \
            else pya.Point(round(t.point.x / layout.dbu), round(t.point.y / layout.dbu))
        found = None
        for dt in (PIN, 0):
            for poly in shapes[t.layer][dt]:
                if poly.bbox().contains(p) and (poly.inside(p) or poly.bbox().contains(p) and poly.is_box()):
                    found = poly
                    break
            if found is not None:
                break
        if found is None:
            h = int(round(MIN_WIDTH[t.layer] / 2000 / layout.dbu))
            found = pya.Polygon(pya.Box(p.x - h, p.y - h, p.x + h, p.y + h))
        out.setdefault(t.net, []).append((t.layer, found))
    return out


def wire_shapes(layout, top, conn, nets):
    """{net: {metal: [Polygon]}}: each net's merged conductor shapes per metal (flat extraction,
    found from the net's terminals; every piece of an unfinished net)."""
    terms, _ = connectivity.terminals(layout, top, conn)
    l2n, regions = connectivity.extract(layout, top)
    out = {}
    wanted = set(nets)
    seen = {}
    for t in terms:
        if t.net not in wanted or t.layer not in regions:
            continue
        net = l2n.probe_net(regions[t.layer], t.probe)
        if net is None or net.cluster_id in seen.setdefault(t.net, set()):
            continue
        seen[t.net].add(net.cluster_id)
        for metal in METALS:
            polys = list(l2n.shapes_of_net(net, regions[metal], True).merged().each())
            if polys:
                out.setdefault(t.net, {}).setdefault(metal, []).extend(polys)
    return out


# ---- existing pins -------------------------------------------------------------------------------

def existing_pins(top):
    """{name: [(layer index, text shape, [pin shapes under it])]} of the top cell's own pin labels."""
    layout = top.layout()
    out = {}
    for metal in METALS:
        pin_li = layout.find_layer(LAYERS[metal], PIN)
        for dt in (PIN, 2):
            li = layout.find_layer(LAYERS[metal], dt)
            if li is None:
                continue
            for s in top.shapes(li).each(pya.Shapes.STexts):
                under = []
                if pin_li is not None:
                    p = pya.Point(s.text.x, s.text.y)
                    for ps in top.shapes(pin_li).each_touching(pya.Shapes.SBoxes | pya.Shapes.SPolygons,
                                                                pya.Box(p, p)):
                        if ps.polygon is not None and ps.polygon.inside(p):
                            under.append(ps)
                out.setdefault(s.text_string, []).append((li, s, under))
    return out


def remove_pin(top, entries):
    """Delete a pin's labels and the pin shapes they are on (the shapes no other label shares)."""
    gone = set()
    for li, text, under in entries:
        for ps in under:
            key = (ps.layer, str(ps.bbox()))
            if key in gone or not ps.is_valid():
                continue
            gone.add(key)
            ps.delete()
        if text.is_valid():
            text.delete()


# ---- placing -------------------------------------------------------------------------------------

def plan(top, conn, bits, mode="terminals", edge="auto", metal="auto", align=True, pitch=None, start=None,
         reverse=False):
    """Where each bit's pin goes, without changing the layout:
    ([(bit, metal, DPoint)], [problems]). See place_pins for the arguments."""
    if mode not in MODES:
        raise ValueError(f"mode is one of {', '.join(MODES)}, not {mode}")
    if edge != "auto" and edge not in EDGES:
        raise ValueError(f"edge is auto or one of {', '.join(EDGES)}, not {edge}")
    if mode == "edge" and edge == "auto":
        raise ValueError("pins along a cell edge need the edge: top, bottom, left or right")
    if metal != "auto" and metal not in METALS:
        raise ValueError(f"pins are on metal layers, not {metal}")
    layout = top.layout()
    dbu = layout.dbu
    frame = cell_frame(top)
    problems, out = [], []
    nm = lambda v: int(round(v / 1000 / dbu))             # noqa: E731 - nm -> dbu

    if mode == "wires":
        nets = wire_shapes(layout, top, conn, bits)
        for bit in bits:
            by_metal = nets.get(bit, {})
            m = metal if metal != "auto" else next((x for x in reversed(METALS) if x in by_metal), None)
            if m is None or m not in by_metal:
                problems.append(f"{bit}: no {m.upper() if m else 'metal'} wiring of the net found")
                continue
            _, p, _ = _nearest_end(by_metal[m], frame, edge, nm(MIN_WIDTH[m]))
            out.append((bit, m, p))
    else:
        terms = terminal_shapes(layout, top, conn)
        for i, bit in enumerate(bits if not reverse else list(reversed(bits))):
            shapes = terms.get(bit, [])
            if metal != "auto" and mode == "terminals":
                shapes = [s for s in shapes if s[0] == metal]
            if mode == "terminals":
                if not shapes:
                    problems.append(f"{bit}: no terminal of the net" + (f" on {metal.upper()}" if metal != "auto" else ""))
                    continue
                # the terminal whose end is nearest the edge (several instances on the net)
                ends = [(_nearest_end([poly], frame, edge, nm(MIN_WIDTH[m])), m) for m, poly in shapes]
                (_, p, _), m = min(ends, key=lambda t: t[0][0])
                out.append((bit, m, p))
                continue
            # along the edge
            if align:
                if not shapes:
                    problems.append(f"{bit}: no terminal of the net to align the pin with")
                    continue
                best = None
                for m, poly in shapes:
                    along, _, end = _end(poly, edge, nm(MIN_WIDTH[m]))
                    key = _gap(frame, edge, end)
                    if best is None or key < best[0]:
                        best = (key, m, along)
                m, along = (best[1] if metal == "auto" else metal), best[2]
            else:
                if metal == "auto":
                    raise ValueError("evenly spaced pins need their metal")
                m = metal
                low = frame.left if edge in ("top", "bottom") else frame.bottom
                along = low + nm(start if start is not None else PITCH[m]) + i * nm(pitch or PITCH[m])
            h = nm(MIN_WIDTH[m]) // 2
            across = {"top": frame.top - h, "bottom": frame.bottom + h,
                      "right": frame.right - h, "left": frame.left + h}[edge]
            if m in TRACKS:
                # the coordinate across the metal's routing direction goes onto a track; across the
                # edge, the nearest track that keeps the pin inside the cell
                along_is_across_metal = (m in VERTICAL) == (edge in ("top", "bottom"))
                if along_is_across_metal:
                    along = _snap_track(along, m, dbu)
                else:
                    across = _snap_track(across, m, dbu, "down" if edge in ("top", "right") else "up")
            low, high = (frame.left, frame.right) if edge in ("top", "bottom") else (frame.bottom, frame.top)
            if not low + h <= along <= high - h:
                problems.append(f"{bit}: its terminal is off the {edge} side" if align else
                                f"{bit}: past the end of the {edge} side ({len(bits)} pins at this pitch and start "
                                "do not fit)")
                continue
            out.append((bit, m, _point(edge, along, across)))
    return [(b, m, p.to_dtype(dbu)) for b, m, p in out], problems


def check_spacing(placed):
    """Pairs of pins on the same metal closer than its minimum width (their squares overlap or
    nearly touch): [message]."""
    msgs = []
    by_metal = {}
    for bit, m, p in placed:
        by_metal.setdefault(m, []).append((bit, p))
    for m, pins in by_metal.items():
        need = 2 * MIN_WIDTH[m] / 1000 - 1e-6           # centre to centre: width + spacing (= width)
        pins.sort(key=lambda t: (t[1].x, t[1].y))
        for i, (a, pa) in enumerate(pins):
            for b, pb in pins[i + 1:]:
                if pb.x - pa.x >= need:
                    break
                if abs(pb.y - pa.y) < need:
                    msgs.append(f"{a} and {b} pins on {m.upper()} are {round(pa.distance(pb) * 1000)} nm apart")
    return msgs


def off_metal(top, placed):
    """Bits whose pin is not on drawn metal of its layer (DRC OL.PIN until the wire is drawn)."""
    layout = top.layout()
    drawn = {}
    out = []
    for bit, m, p in placed:
        if m not in drawn:
            li = layout.find_layer(LAYERS[m], 0)
            drawn[m] = pya.Region(top.begin_shapes_rec(li)).merged() if li is not None else pya.Region()
        h = MIN_WIDTH[m] / 2000
        box = pya.DBox(p.x - h, p.y - h, p.x + h, p.y + h).to_itype(layout.dbu)
        if not (pya.Region(box) - drawn[m]).is_empty():
            out.append(bit)
    return out


def place_pins(top, conn, names, mode="terminals", edge="auto", metal="auto", align=True, pitch=None,
               start=None, reverse=False, replace=True):
    """Place the pins of `names` (buses, ranges, bits - see the module doc) in cell `top`.

    conn: the schematic link (connectivity.load_conn); its ports name the pins, its terminals
          place them.
    mode: "terminals" | "wires" | "edge" (module doc). edge: "top" | "bottom" | "left" | "right",
          or "auto" (terminals / wires: the end nearest any side of the cell).
    metal: "m1" ... "m9"; "auto" = the terminal's own metal (terminals, aligned edge pins) or the
          net's top metal (wires).
    align (edge): at the net's terminals along the side; else evenly spaced, pitch nm apart (default
          the metal's track pitch) from start nm past the cell's left / bottom side, in port order
          (reverse: the other way round).
    replace: move pins of these names that exist already; else leave them (reported as skipped).

    Returns {"placed": [(bit, metal, DPoint)], "moved": [bits], "skipped": [bits], "problems": [],
    "warnings": [], "off_metal": [bits]}."""
    bits, unknown = resolve(names, conn.get("ports") if conn else None)
    problems = [f"{u}: not a pin of the schematic" for u in unknown]
    have = existing_pins(top)
    skipped = [b for b in bits if b in have and not replace]
    todo = [b for b in bits if b not in skipped]
    placed, more = plan(top, conn, todo, mode, edge, metal, align, pitch, start, reverse)
    problems += more
    from .generate import _add_pin
    moved = []
    for bit, m, p in placed:
        if bit in have:
            remove_pin(top, have[bit])
            moved.append(bit)
        _add_pin(top, bit, p, m)
    return {"placed": placed, "moved": moved, "skipped": skipped, "problems": problems,
            "warnings": check_spacing(placed), "off_metal": off_metal(top, placed)}


def place_pins_file(gds, names, out=None, cell=None, **options):
    """Batch: place pins in a layout file (its schematic link next to it) and write it to `out`
    (default: back to `gds`). Returns place_pins' report."""
    from .pcells import register_library
    register_library()                      # before reading: PCells stay PCells
    layout = pya.Layout()
    layout.technology_name = "asap7"
    layout.read(str(gds))
    top = layout.cell(cell) if cell else layout.top_cell()
    conn = connectivity.load_conn(gds)
    if conn is None:
        raise RuntimeError(f"no schematic link {connectivity.conn_file(gds).name} next to {gds}")
    report = place_pins(top, conn, names, **options)
    layout.write(str(out or gds))
    return report


def describe(report):
    """One line for the status bar."""
    parts = [f"{len(report['placed'])} pins placed"]
    if report["moved"]:
        parts.append(f"{len(report['moved'])} moved")
    if report["skipped"]:
        parts.append(f"{len(report['skipped'])} existing left alone")
    if report["off_metal"]:
        parts.append(f"{len(report['off_metal'])} not yet on drawn metal (OL.PIN)")
    if report["warnings"]:
        parts.append(f"{len(report['warnings'])} too close")
    if report["problems"]:
        parts.append(f"{len(report['problems'])} not placed")
    return ", ".join(parts)
